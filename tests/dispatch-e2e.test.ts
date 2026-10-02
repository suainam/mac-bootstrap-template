/**
 * End-to-end integration — TB-07.
 *
 * Exercises the whole pipeline across both surfaces in one scenario, because
 * the unit suites deliberately test each surface in isolation:
 *
 *   start -> park -> heartbeat -> heartbeat ... -> [NOTIFY] -> synthesis
 *         -> stalled lane -> cold start -> orphan + resume validation
 *
 * The two surfaces never call each other. The Herdr side is one-shot argv
 * commands reading the shared state file; the omp side is in-process. This test
 * wires them through a real state document on disk, which is the only coupling
 * that exists in production too.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { describe, expect, test } from "bun:test";

import dispatchBrain, {
  laneFromSignature,
} from "../agent/omp/extensions/dispatch-omp/index.ts";

const PLUGIN_ROOT = path.resolve(import.meta.dir, "../multiplexer/herdr-dispatch");
/**
 * Resolve a Python that can import the plugin.
 *
 * The system python3 is older than the version this repository targets, and
 * the plugin modules use modern syntax. Prefer an explicit override, then the
 * repo virtualenv, then any interpreter new enough.
 */
function resolvePython(): string {
  // No absolute path: a checked-in test must not carry an owner-specific path.
  const candidates = [
    process.env.DISPATCH_TEST_PYTHON,
    path.resolve(import.meta.dir, "../.venv/bin/python"),
    "python3.13",
    "python3.12",
    "python3",
  ].filter(Boolean) as string[];
  for (const candidate of candidates) {
    try {
      const out = execFileSync(candidate, ["-c", "import sys; print(sys.version_info >= (3, 10))"], {
        encoding: "utf8",
      });
      if (out.trim() === "True") return candidate;
    } catch {
      // Try the next candidate.
    }
  }
  return "python3";
}

const PYTHON = resolvePython();

/** A state document plus the repo that anchors it. */
function makeRun(initial: Record<string, unknown> = {}) {
  const dir = mkdtempSync(path.join(tmpdir(), "dispatch-e2e-"));
  const repo = path.join(dir, "repo");
  mkdirSync(repo, { recursive: true });
  execFileSync("git", ["init", "-q", repo]);
  const statePath = path.join(repo, ".git", "dispatch", "ORCHESTRATOR_STATE.json");
  mkdirSync(path.dirname(statePath), { recursive: true });
  writeFileSync(
    statePath,
    JSON.stringify({
      schema: 2,
      orchestrator_phase: "contract",
      lanes: {},
      brain: { awaiting_lanes: [], notifications_seen: 0 },
      ...initial,
    }),
  );
  return { repo, statePath, read: () => JSON.parse(readFileSync(statePath, "utf8")) };
}

function writeState(statePath: string, state: Record<string, unknown>) {
  writeFileSync(statePath, JSON.stringify(state, null, 2));
}

/** Run a plugin command the way Herdr would: fresh process, argv only. */
function runPlugin(args: string[], env: Record<string, string> = {}) {
  return execFileSync(
    PYTHON,
    [path.join(PLUGIN_ROOT, "bin", "dispatch_plugin.py"), ...args],
    { encoding: "utf8", env: { ...process.env, ...env } },
  );
}

/** The omp-side host, with a read-only pane registry. */
function makeHost(cwd: string, panes: Record<string, Record<string, unknown>> = {}) {
  const calls = { messages: [] as Array<{ text: string; options?: unknown }>, notes: [] as string[] };
  const handlers = new Map<string, (event: unknown, ctx: unknown) => unknown>();
  const host = {
    calls,
    on(name: string, fn: (event: unknown, ctx: unknown) => unknown) {
      handlers.set(name, fn);
      return host;
    },
    setLabel() {},
    ui: {
      notify(message: string) {
        calls.notes.push(message);
      },
    },
    sendUserMessage(text: string, options?: unknown) {
      calls.messages.push({ text, options });
    },
    // Read-only: the watchdog may look, never write.
    herdrAgentInfo: (paneId: string) => panes[paneId] ?? null,
  };
  const ctx = {
    hasUI: true,
    cwd,
    agent: { kind: "main" },
    isIdle: () => true,
    ui: host.ui,
    setInterval: () => ({ id: 1 }),
    clearTimer: () => {},
  };
  return {
    host,
    ctx,
    emit: (name: string, event: Record<string, unknown> = {}) =>
      handlers.get(name)?.(event, ctx),
  };
}

const NOTIFY = (lane: string) =>
  `\n[NOTIFY] [${lane}_opencode_e2e-repo]\nDONE: lane finished\nHandoff: /tmp/h.md`;
const BEAT = (lane: string, stage = "Stage 2 Reviewing on hk96") =>
  `\n[HEARTBEAT] [${lane}_opencode_e2e-repo]\nSTAGE: ${stage}\nPROGRESS: 1/2`;

// --------------------------------------------------------------------------

describe("end-to-end: park, heartbeat, notify, synthesis", () => {
  test("the state document records the park the extension is holding", async () => {
    // The park is established by the orchestrator through the Python state
    // store; this asserts the shared document is what both sides read, and
    // that the extension sees the same park the plugin would render.
    const { repo, statePath, read } = makeRun();
    const run = makeHost(repo);

    // Park via the plugin-side state store (the authoritative writer).
    execFileSync(
      PYTHON,
      [path.join(PLUGIN_ROOT, "lib", "orchestrator_state.py"), "advance", "--repo", repo, "--to", "topology"],
      { encoding: "utf8" },
    );
    execFileSync(
      PYTHON,
      [path.join(PLUGIN_ROOT, "lib", "orchestrator_state.py"), "park", "--repo", repo, "--pane", "w3:p1", "--lane", "w3:p5"],
      { encoding: "utf8" },
    );

    expect(read().orchestrator_phase).toBe("yield_and_guard");
    expect(read().brain.awaiting_lanes).toEqual(["w3:p5"]);

    const brain = dispatchBrain(run.host);
    await run.emit("session_start");
    // Adopt the park the plugin-side store established; the extension must
    // see exactly what the plugin would render.
    brain.setState(read());
    expect(brain.getState().orchestrator_phase).toBe("yield_and_guard");
    expect(brain.getState().brain.awaiting_lanes).toEqual(["w3:p5"]);
    void statePath;
  });

  test("a heartbeat is absorbed without ending the park", async () => {
    const { repo } = makeRun();
    const run = makeHost(repo);
    const brain = dispatchBrain(run.host);
    await run.emit("session_start");
    brain.setState({
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["w3:p5"], notifications_seen: 0 },
    });

    const result = brain.consumeHeartbeat(BEAT("w3:p5"));
    expect(result.ok).toBe(true);
    // The whole point: liveness evidence must not hand work back.
    expect(result.stillParked).toBe(true);
    expect(brain.getState().orchestrator_phase).toBe("yield_and_guard");
    expect(result.sidebarToken).toEqual({ dstate: "s2@hk96" });
    expect(brain.getHeartbeats()).toHaveLength(1);
  });

  test("a report ends the park and advances to synthesis", async () => {
    const { repo } = makeRun();
    const run = makeHost(repo);
    const brain = dispatchBrain(run.host);
    await run.emit("session_start");
    brain.setState({
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["w3:p5"], notifications_seen: 0 },
    });

    const result = brain.consumeNotify(NOTIFY("w3:p5"));
    expect(result.ok).toBe(true);
    expect(result.transitioned).toBe(true);
    expect(brain.getState().orchestrator_phase).toBe("synthesis");
    expect(brain.getState().brain.notifications_seen).toBe(1);
    expect(brain.getInbox()).toHaveLength(1);
    // The steer must demand reconciliation, not restatement.
    const steer = run.host.calls.messages.at(-1);
    expect(steer?.text).toContain("synthesis");
    expect(steer?.options).toMatchObject({ deliverAs: "aside", attribution: "agent" });
  });

  test("heartbeats before the report do not shorten the park", async () => {
    const { repo } = makeRun();
    const run = makeHost(repo);
    const brain = dispatchBrain(run.host);
    await run.emit("session_start");
    brain.setState({
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["w3:p5"], notifications_seen: 0 },
    });

    for (const stage of ["Stage 1 Planning", "Stage 2 Reviewing on hk96", "Stage 3 Verifying"]) {
      brain.consumeHeartbeat(BEAT("w3:p5", stage));
      expect(brain.getState().orchestrator_phase).toBe("yield_and_guard");
    }
    expect(brain.getHeartbeats()).toHaveLength(3);

    brain.consumeNotify(NOTIFY("w3:p5"));
    expect(brain.getState().orchestrator_phase).toBe("synthesis");
    expect(brain.getState().brain.notifications_seen).toBe(1);
  });

  test("a todo reminder never ends the park", async () => {
    const { repo } = makeRun();
    const run = makeHost(repo);
    const brain = dispatchBrain(run.host);
    await run.emit("session_start");
    brain.setState({
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["w3:p5"], notifications_seen: 0 },
    });

    for (let i = 0; i < 20; i += 1) {
      await run.emit("todo_reminder");
    }
    // Twenty reminders, still parked. This is the loop that used to burn tokens.
    expect(brain.getState().orchestrator_phase).toBe("yield_and_guard");
    const guard = run.host.calls.messages.at(-1);
    expect(guard?.text).toContain("deliberate suspension");
  });
});

// --------------------------------------------------------------------------

describe("end-to-end: watchdog and cold start", () => {
  test("a stalled lane alarms once, not every poll", async () => {
    const { repo, statePath } = makeRun({
      lanes: { "w3:p5": { lane: "1-1", pane_id: "w3:p5" } },
    });
    const run = makeHost(repo, {
      "w3:p5": { agent_status: "working", state_change_seq: 9 },
    });
    const brain = dispatchBrain(run.host);
    await run.emit("session_start");
    brain.setState({
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["w3:p5"], notifications_seen: 0 },
    });
    void statePath;

    for (let i = 0; i < 12; i += 1) brain.tick();
    const alarms = run.host.calls.messages.filter((m) => m.text.includes("no state change"));
    expect(alarms).toHaveLength(1);

    // Further polls must stay quiet until the lane shows progress again.
    for (let i = 0; i < 10; i += 1) brain.tick();
    expect(
      run.host.calls.messages.filter((m) => m.text.includes("no state change")),
    ).toHaveLength(1);
  });

  test("a heartbeat resets one lane without masking another", async () => {
    const { repo } = makeRun({
      lanes: {
        "w3:p5": { lane: "1-1", pane_id: "w3:p5" },
        "w3:p4": { lane: "1-2", pane_id: "w3:p4" },
      },
    });
    const run = makeHost(repo, {
      "w3:p5": { agent_status: "working", state_change_seq: 1 },
      "w3:p4": { agent_status: "working", state_change_seq: 1 },
    });
    const brain = dispatchBrain(run.host);
    await run.emit("session_start");
    brain.setState({
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["w3:p5", "w3:p4"], notifications_seen: 0 },
    });

    for (let i = 0; i < 12; i += 1) {
      // Only lane w3:p5 keeps reporting in.
      brain.consumeHeartbeat(BEAT("w3:p5", "Stage 1 Planning"));
      brain.tick();
    }
    const alarms = run.host.calls.messages.filter((m) => m.text.includes("no state change"));
    expect(alarms.length).toBeGreaterThan(0);
    // The chatty lane is never named; the quiet one is.
    expect(alarms.some((m) => m.text.includes("w3:p4"))).toBe(true);
    expect(alarms.some((m) => m.text.includes("w3:p5"))).toBe(false);
  });

  test("cold start orphans a lost pane and validates resume commands", async () => {
    const { repo } = makeRun({
      lanes: {
        "1-1": {
          lane: "1-1",
          pane_id: "w3:p5",
          expected_resume_argv: ["omp", "--resume", "sess-1"],
        },
        "1-2": {
          lane: "1-2",
          pane_id: "w3:p9",
          expected_resume_argv: ["omp", "--resume", "it's-bad"],
        },
      },
    });
    // Only w3:p5 came back after the restart.
    const run = makeHost(repo, {
      "w3:p5": { agent_status: "idle", state_change_seq: 5 },
    });
    const brain = dispatchBrain(run.host);
    await run.emit("session_start");

    const cold = brain.getColdStart();
    expect(cold.live.map((l: { laneId: string }) => l.laneId)).toEqual(["1-1"]);
    expect(cold.orphaned.map((o: { laneId: string }) => o.laneId)).toEqual(["1-2"]);
    expect(cold.orphaned[0].reason).toBe("pane absent");

    // Valid command passes; the apostrophe one is rejected with a reason.
    expect(cold.resume).toHaveLength(2);
    const good = cold.resume.find((r: { laneId: string }) => r.laneId === "1-1");
    const bad = cold.resume.find((r: { laneId: string }) => r.laneId === "1-2");
    expect(good.ok).toBe(true);
    expect(bad.ok).toBe(false);
    expect(bad.reason).toContain("apostrophe");
  });
});

// --------------------------------------------------------------------------

describe("end-to-end: the two surfaces", () => {
  test("the plugin reads what the extension wrote, without importing it", async () => {
    // Seed the lane document the way the extension would have written it after
    // absorbing a heartbeat.
    const { repo, statePath } = makeRun({
      orchestrator_phase: "yield_and_guard",
      lanes: {
        "1-1": {
          lane: "1-1",
          pane_id: "w3:p5",
          status: "working",
          current_stage: "Stage 4 Deploying on hk216",
          last_heartbeat: 1_700_000_000_000,
        },
      },
    });
    const run = makeHost(repo, { "w3:p5": { agent_status: "working", state_change_seq: 4 } });
    const brain = dispatchBrain(run.host);
    await run.emit("session_start");
    brain.setState({
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["w3:p5"], notifications_seen: 0 },
    });
    expect(JSON.parse(readFileSync(statePath, "utf8")).lanes["1-1"]).toBeDefined();

    // The plugin side reads the same document and renders it, with no import
    // of anything omp-side.
    const out = runPlugin(["--repo", repo, "status", "--json"]);
    const doc = JSON.parse(out);
    expect(doc.orchestrator_phase).toBe("yield_and_guard");
    expect(Object.keys(doc.lanes)).toContain("1-1");
    // The heartbeat evidence the extension records must survive the round trip
    // through the plugin's reader.
    expect(doc.lanes["1-1"].current_stage).toContain("Stage 4");
    expect(typeof doc.lanes["1-1"].last_heartbeat).toBe("number");
  });

  test("the board renders the shared document", async () => {
    const { repo, statePath } = makeRun({
      orchestrator_phase: "yield_and_guard",
      blocked_reason: "Awaiting worker IPC [NOTIFY] on w3:p5",
      brain: { awaiting_lanes: ["w3:p5"], notifications_seen: 1 },
      lanes: {
        "1-1": { lane: "1-1", wave: 1, role: "writer", kind: "omp", status: "working", pane_id: "w3:p5" },
      },
    });
    void statePath;
    const out = execFileSync(
      PYTHON,
      [path.join(PLUGIN_ROOT, "bin", "dispatch_board.py"), "--repo", repo, "--once", "--json"],
      { encoding: "utf8" },
    );
    const view = JSON.parse(out);
    expect(view.brain).toBe("yield_and_guard");
    expect(view.rows[0].lane).toBe("1-1");
    expect(view.rows[0].role).toBe("writer");
  });

  test("the signature the bus derives is one the extension can attribute", async () => {
    // The full round trip: the bus parks the brain on a lane id and hands the
    // worker a report signature; the extension has to resolve that signature
    // back to the same lane id for the park to open.
    //
    // This is the defect a unit test on either side would miss. Both halves can
    // be individually correct — the brain keys on `1-3`, the report reads as a
    // lane key — and still never meet, because the bus parks on a lane id while
    // the worker reports with whatever it was told to put in the signature.
    const dir = mkdtempSync(path.join(tmpdir(), "dispatch-roundtrip-"));
    const repo = path.join(dir, "repo");
    mkdirSync(repo, { recursive: true });
    execFileSync("git", ["init", "-q", repo]);
    execFileSync("git", ["-C", repo, "checkout", "-q", "-b", "feat/1-3"]);
    writeFileSync(path.join(repo, "seed"), "seed");
    execFileSync("git", ["-C", repo, "add", "seed"]);
    execFileSync("git", ["-C", repo, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "-m", "seed"]);

    writeFileSync(
      path.join(repo, "TASK.md"),
      [
        "# 目标 (Outcome)",
        "实施总线参数精简并通过全量测试。",
        "",
        "# 验证 (Verification)",
        "pytest tests/",
        "",
        "# 约束 (Constraints)",
        "不得写入任何凭证。",
        "",
        "# 边界 (Boundaries)",
        "仅修改插件目录。",
        "",
        "# 迭代策略 (Iteration Policy)",
        "使用 rtk 控制输出, 走 to-spec 与 implement-spec",
        "",
        "# 完成条件 (Stop when)",
        "全部测试通过。",
        "",
        "# 暂停条件 (Pause if)",
        "遇到跨平台路径歧义立即暂停。",
        "",
      ].join("\n"),
    );

    // A stub Herdr so the bus can read the pane's cwd and record the delivery.
    const delivered = path.join(dir, "delivered.txt");
    const stub = path.join(dir, "herdr");
    writeFileSync(
      stub,
      [
        "#!/usr/bin/env python3",
        "import json, sys",
        "argv = sys.argv[1:]",
        "if argv[:2] == ['pane', 'get']:",
        `    print(json.dumps({'result': {'pane': {'pane_id': argv[2], 'cwd': ${JSON.stringify(repo)}}}}))`,
        "elif argv[:2] == ['agent', 'prompt']:",
        `    open(${JSON.stringify(delivered)}, 'a').write(argv[3] + '\\n')`,
        "else:",
        "    print('{}')",
        "",
      ].join("\n"),
    );
    execFileSync("chmod", ["+x", stub]);

    const previousBin = process.env.HERDR_BIN_PATH;
    const previousSocket = process.env.HERDR_SOCKET_PATH;
    process.env.HERDR_BIN_PATH = stub;
    delete process.env.HERDR_SOCKET_PATH;
    try {
      runPlugin([
        "--repo", repo,
        "dispatch",
        "--task", path.join(repo, "TASK.md"),
        "--lane-name", "1-3-dispatch",
        "--target", "w3:p9",
        "--callback-target", "w3:pB",
      ]);
    } finally {
      if (previousBin === undefined) delete process.env.HERDR_BIN_PATH;
      else process.env.HERDR_BIN_PATH = previousBin;
      if (previousSocket === undefined) delete process.env.HERDR_SOCKET_PATH;
      else process.env.HERDR_SOCKET_PATH = previousSocket;
    }

    // The bus parked on a lane id...
    const state = JSON.parse(
      readFileSync(path.join(repo, ".git", "dispatch", "ORCHESTRATOR_STATE.json"), "utf8"),
    );
    expect(state.orchestrator_phase).toBe("yield_and_guard");
    expect(state.brain.awaiting_lanes).toEqual(["1-3"]);

    // ...and handed the worker a request carrying a signature the extension
    // can later attribute when the worker emits its [NOTIFY] return leg.
    const request = readFileSync(delivered, "utf8");
    expect(request).toContain("[DISPATCH]");
    const signature = request.match(/^Signature:\s*(\S+)$/m)?.[1] ?? "";
    const handoff = request.match(/^Handoff:\s*(\S+)$/m)?.[1] ?? "";
    expect(signature).not.toBe("");
    expect(handoff).not.toBe("");
    expect(laneFromSignature(signature)).toBe("1-3");
    const report = `[NOTIFY] [${signature}]\nDONE: completed\nHandoff: ${handoff}`;

    // Now drive the extension with the canonical completion report.
    const run = makeHost(repo);
    const brain = dispatchBrain(run.host);
    await run.emit("session_start");
    brain.setState(state);

    const result = brain.consumeNotify(report);
    expect(result.ok).toBe(true);
    expect(result.transitioned).toBe(true);
    // The point of the round trip: the park actually opens.
    expect(brain.getState().brain.awaiting_lanes).toEqual([]);
    expect(brain.getState().orchestrator_phase).toBe("synthesis");
  });

  test("the plugin never imports the extension and vice versa", () => {
    // Checked as imports and invocations, not raw substrings: a legacy state
    // glob like ~/.omp/dispatch-omp/ is migration bookkeeping, not a
    // dependency, and flagging it would make the rule unenforceable.
    const pluginCode = ["lib/herdr_client.py", "lib/orchestrator_state.py", "bin/dispatch_board.py", "bin/dispatch_plugin.py"]
      .map((rel) =>
        readFileSync(path.join(PLUGIN_ROOT, rel), "utf8")
          .split("\n")
          // Ignore prose; only executable statements matter.
          .filter((line) => {
            const s = line.trim();
            return s && !s.startsWith("#") && !s.startsWith('"') && !s.startsWith("*");
          })
          .join("\n"),
      )
      .join("\n");
    expect(/^\s*(import|from)\s+.*dispatch[-_]omp/m.test(pluginCode)).toBe(false);
    expect(pluginCode.includes("subprocess") && pluginCode.includes("dispatch-omp")).toBe(false);

    const extCode = ["index.ts", "notify.ts", "heartbeat.ts", "ledger.ts", "slash.ts"]
      .map((rel) =>
        readFileSync(
          path.resolve(import.meta.dir, "../agent/omp/extensions/dispatch-omp", rel),
          "utf8",
        )
          .split("\n")
          .filter((line) => {
            const s = line.trim();
            return s && !s.startsWith("//") && !s.startsWith("*");
          })
          .join("\n"),
      )
      .join("\n");
    // The extension may read pane state, never drive Herdr.
    expect(extCode.includes("HERDR_BIN_PATH")).toBe(false);
    expect(extCode.includes("report_metadata")).toBe(false);
    expect(extCode.includes("report-agent")).toBe(false);
    expect(/spawnSync\(\s*["\']herdr/.test(extCode)).toBe(false);
  });
});