/**
 * Tests for the omp-side brain loop — TB-04.
 *
 * Run with:  bun test agent/omp/extensions/dispatch-omp/
 *
 * The fake host below reproduces the behaviours that actually matter for
 * safety, taken from omp's documented runtime model rather than invented:
 *
 * - a raw `setInterval` callback that throws becomes a process-level
 *   `uncaughtException`, which the global postmortem treats as fatal and
 *   which tears down the whole session;
 * - a `ctx.setInterval` callback is isolated, reported, and keeps the session
 *   alive;
 * - restricted subagent sessions rebind the parent's factories, so guards must
 *   key off session identity rather than a module-level flag or nesting depth.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { describe, expect, test } from "bun:test";

import dispatchBrain, {
  BRAIN_PHASES,
  BRAIN_TRANSITIONS,
  DEFAULT_ROUTING,
  PHASE0_TODOS,
  RouterCursor,
  WAKE_SIGNALS,
  buildPhase0Todos,
  checkTransition,
  classifyToolCall,
  chooseModel,
  isParked,
  loadRouting,
  lookupHerdrAgent,
  parkGuardMessage,
  resolveStatePath,
} from "../agent/omp/extensions/dispatch-omp/index.ts";

/**
 * Build a real repository with a dispatch state file.
 *
 * The watchdog reads lanes from the shared state file rather than from
 * in-memory session state, so exercising it honestly means a real git repo and
 * a real document. Anchoring on the git common dir is what makes that work
 * across worktrees.
 */
function makeRepoWithState(state: Record<string, unknown>) {
  const dir = mkdtempSync(path.join(tmpdir(), "dispatch-tick-"));
  const repo = path.join(dir, "repo");
  mkdirSync(repo, { recursive: true });
  execFileSync("git", ["init", "-q", repo]);
  const statePath = path.join(repo, ".git", "dispatch", "ORCHESTRATOR_STATE.json");
  mkdirSync(path.dirname(statePath), { recursive: true });
  writeFileSync(statePath, JSON.stringify(state));
  return { repo, statePath };
}

/** Records what the extension asked the host to do. */
function makeHost({ agent = { kind: "main" }, hasUI = true, cwd = "/repo" } = {}) {
  const calls = {
    messages: [],
    notifications: [],
    statuses: [],
    intervals: [],
    clearedTimers: 0,
    labels: [],
  };
  let handlerSeq = 0;
  const handlers = new Map();
  const paneInfo = new Map();

  const host = {
    calls,
    handlers,
    paneInfo,
    setPane(paneId, info) {
      paneInfo.set(paneId, info);
      return this;
    },
    on(name, fn) {
      handlers.set(name, fn);
      return this;
    },
    register(name, fn) {
      handlers.set(name, fn);
    },
    emit(name, event = {}, extra = {}) {
      const fn = handlers.get(name);
      if (!fn) return undefined;
      // Documented: managed timers and the UI are on the handler context.
      const ctx = {
        hasUI,
        cwd,
        agent,
        isIdle: () => true,
        ui: host.ui,
        setInterval(fn2, ms) {
          const handle = { id: ++handlerSeq, fn: fn2, ms, kind: "managed" };
          calls.intervals.push(handle);
          return handle;
        },
        setTimeout(fn2, ms) {
          const handle = { id: ++handlerSeq, fn: fn2, ms, kind: "managed" };
          calls.intervals.push(handle);
          return handle;
        },
        clearTimer(handle) {
          if (handle) calls.clearedTimers += 1;
        },
        ...extra,
      };
      return fn(event, ctx);
    },
    async emitAsync(name, event = {}, extra = {}) {
      return await this.emit(name, event, extra);
    },
    // Documented timers: isolated, tracked, cleared on shutdown.
    ui: {
      notify(message, level) {
        calls.notifications.push({ message, level });
      },
      setStatus(key, value) {
        calls.statuses.push({ key, value });
      },
    },
    setLabel(label) {
      calls.labels.push(label);
    },
    sendUserMessage(text, options) {
      calls.messages.push({ text, options });
    },
  };
  return host;
}

function boot(options: any = {}) {
  const { lookupPane: lookupOverride, ...hostOptions } = options;
  const pi = makeHost(hostOptions);
  const lookupPane =
    lookupOverride ??
    ((paneId: string) =>
      pi.paneInfo.has(paneId)
        ? { status: "known", info: pi.paneInfo.get(paneId) }
        : { status: "absent", reason: "agent_not_found" });
  const brain = dispatchBrain(pi, { lookupPane });
  return { pi, brain };
}

// --------------------------------------------------------------------------
// Transition guards — the false-busywork and no-auto-publish invariants
// --------------------------------------------------------------------------

describe("brain transitions", () => {
  test("the full loop is walkable", async () => {
    expect(checkTransition("contract", "topology")).toBeNull();
    expect(checkTransition("topology", "yield_and_guard")).toBeNull();
    expect(checkTransition("yield_and_guard", "synthesis", "notify")).toBeNull();
    expect(checkTransition("synthesis", "decision")).toBeNull();
    expect(checkTransition("decision", "human_gate")).toBeNull();
    expect(checkTransition("human_gate", "closed", "human")).toBeNull();
  });

  test("closed is terminal", async () => {
    expect(BRAIN_TRANSITIONS.closed).toEqual([]);
    expect(checkTransition("closed", "contract", "human")).toMatch(/illegal transition/);
  });

  test("a todo reminder cannot wake the orchestrator", async () => {
    for (const bogus of [undefined, null, "", "todo_reminder", "reminder", "poll"]) {
      expect(checkTransition("yield_and_guard", "synthesis", bogus)).toMatch(
        /todo reminder is not one/,
      );
    }
  });

  test("only real wake signals may leave the park", async () => {
    for (const signal of WAKE_SIGNALS) {
      expect(checkTransition("yield_and_guard", "synthesis", signal)).toBeNull();
    }
  });

  test("human_gate cannot be crossed automatically", async () => {
    for (const automatic of [undefined, "notify", "stall_alarm"]) {
      expect(checkTransition("human_gate", "closed", automatic)).toMatch(
        /explicit human authorisation/,
      );
    }
  });

  test("illegal skips are refused", async () => {
    expect(checkTransition("contract", "human_gate")).toMatch(/illegal transition/);
    expect(checkTransition("contract", "synthesis")).toMatch(/illegal transition/);
  });

  test("unknown phases are refused", async () => {
    expect(checkTransition("contract", "vibes")).toMatch(/unknown orchestrator phase/);
    expect(BRAIN_PHASES).not.toContain("vibes");
  });

  test("a no-op transition is allowed", async () => {
    expect(checkTransition("contract", "contract")).toBeNull();
  });
});

describe("parked state", () => {
  test("isParked only matches yield_and_guard", async () => {
    expect(isParked({ orchestrator_phase: "yield_and_guard" })).toBe(true);
    expect(isParked({ orchestrator_phase: "contract" })).toBe(false);
    expect(isParked(undefined)).toBe(false);
  });

  test("the guard message names the lanes and forbids self-assignment", async () => {
    const message = parkGuardMessage({
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["1-1", "1-2"] },
    });
    expect(message).toContain("1-1, 1-2");
    expect(message).toContain("do not start new work");
    expect(message).toContain("do not edit worker-owned files");
  });

  test("the guard message copes with no lanes recorded", async () => {
    expect(parkGuardMessage({ orchestrator_phase: "yield_and_guard" })).toContain("workers");
  });
});

describe("phase 0 meta-tasks", () => {
  test("all six brain states are represented in order", async () => {
    const phases = PHASE0_TODOS.map((t) => t.phase);
    expect(phases).toEqual([
      "contract",
      "topology",
      "yield_and_guard",
      "synthesis",
      "decision",
      "human_gate",
    ]);
  });

  test("the rendered shape matches omp's todo phase shape", async () => {
    const [phase] = buildPhase0Todos();
    expect(phase.name).toBeString();
    for (const task of phase.tasks) {
      expect(task.content).toBeString();
      expect(["pending", "in_progress"]).toContain(task.status);
    }
  });

  test("the park task is visibly marked as a suspension", async () => {
    const park = PHASE0_TODOS.find((t) => t.phase === "yield_and_guard");
    expect(park.content).toContain("parked");
    expect(park.content).toContain("do not self-assign");
  });
});

// --------------------------------------------------------------------------
// Routing matrix
// --------------------------------------------------------------------------

describe("before_subagent_spawn routing", () => {
  test("a routed role yields model patterns and a reason", async () => {
    const { pi } = boot();
    await pi.emit("session_start");
    const result = await pi.emit("before_subagent_spawn", {
      agent: "researcher",
      invocationKind: "task",
      spawnKey: "k1",
    });
    expect(result.model).toEqual(["@slow"]);
    expect(result.note).toContain("role=researcher");
  });

  test("an unrouted role falls through to the default", async () => {
    expect(chooseModel(DEFAULT_ROUTING, "something-unknown")).toEqual(["@smol"]);
    expect(chooseModel({}, "reviewer")).toBeNull();
  });

  test("a re-entered spawn does not advance the router twice", async () => {
    const cursor = new RouterCursor();
    expect(cursor.shouldAdvance("k1")).toBe(true);
    expect(cursor.shouldAdvance("k1")).toBe(false);
    expect(cursor.shouldAdvance("k2")).toBe(true);
  });

  test("N distinct children advance the router exactly N times", async () => {
    const { pi } = boot();
    await pi.emit("session_start");
    for (let i = 0; i < 5; i += 1) {
      await pi.emit("before_subagent_spawn", { agent: "writer", spawnKey: `k${i}` });
    }
    const spawns = pi.handlers.get("before_subagent_spawn");
    expect(spawns).toBeDefined();
    const dup = await pi.emit("before_subagent_spawn", { agent: "writer", spawnKey: "k0" });
    expect(dup).toBeUndefined();
  });

  test("subagent sessions are not routed", async () => {
    const { pi } = boot({ agent: { kind: "sub", name: "explore", depth: 0 } });
    await pi.emit("session_start");
    const result = await pi.emit("before_subagent_spawn", { agent: "writer", spawnKey: "k9" });
    expect(result).toBeUndefined();
  });

  test("an empty pattern list is treated as unrouted", async () => {
    expect(chooseModel({ x: { patterns: [] } }, "x")).toBeNull();
    expect(chooseModel({ x: { patterns: [] } }, "unknown")).toBeNull();
    expect(chooseModel(null, "writer")).toBeNull();
  });
});

// --------------------------------------------------------------------------
// Human gate
// --------------------------------------------------------------------------

describe("tool_call human gate", () => {
  test("destructive operations are blocked", async () => {
    const { pi } = boot();
    await pi.emit("session_start");
    for (const command of [
      "git push origin main",
      "gh pr merge 12",
      "terraform apply",
      "kubectl delete pod x",
      "rm -rf /",
      "git push --force",
    ]) {
      const result = await pi.emit("tool_call", { toolName: "bash", input: { command } });
      expect(result?.block ?? false).toBe(true);
      expect(result?.reason ?? "").toContain("human_gate");
    }
  });

  test("ordinary work is untouched", async () => {
    expect(classifyToolCall("bash", { command: "make check" }).gated).toBe(false);
    expect(classifyToolCall("bash", { command: "git status" }).gated).toBe(false);
    expect(classifyToolCall("bash", { command: "pytest -q" }).gated).toBe(false);
  });

  test("non-shell tools are never gated", async () => {
    expect(classifyToolCall("read", { command: "git push" }).gated).toBe(false);
  });

  test("the block reason names the offending pattern", async () => {
    const verdict = classifyToolCall("bash", { command: "git push origin main" });
    expect(verdict.gated).toBe(true);
    expect(verdict.reason).toContain("destructive operation");
  });
});

// --------------------------------------------------------------------------
// Crash safety — the hard requirement
// --------------------------------------------------------------------------

describe("crash safety", () => {
  test("every timer is a managed timer, never a raw interval", async () => {
    const { pi } = boot();
    await pi.emit("session_start");
    expect(pi.calls.intervals.length).toBeGreaterThan(0);
    for (const handle of pi.calls.intervals) {
      expect(handle.kind).toBe("managed");
    }
  });

  test("a throwing watchdog tick does not take the session down", async () => {
    // omp's rule: an escaping callback throw becomes a fatal
    // uncaughtException that tears down the whole session. The tick is
    // therefore wrapped, so a failure is reported and the loop survives.
    const { pi, brain } = boot();
    await pi.emit("session_start");

    // Make the poll itself explode on every field read.
    brain.setState({
      get orchestrator_phase() {
        throw new Error("watchdog exploded");
      },
    });

    let fatal = null;
    try {
      pi.calls.intervals[0].fn();
      pi.calls.intervals[0].fn();
    } catch (error) {
      fatal = error;
    }

    expect(fatal).toBeNull();
    expect(pi.calls.notifications.some((n) => n.message.includes("watchdog exploded"))).toBe(
      true,
    );
  });

  test("the watchdog keeps running after a failed tick", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    const handle = pi.calls.intervals[0];
    brain.setState({
      get orchestrator_phase() {
        throw new Error("still broken");
      },
    });
    handle.fn();
    // A dead watchdog would be a silent failure; the next tick must still fire.
    expect(() => handle.fn()).not.toThrow();
  });

  test("a throwing notification cannot break session start", async () => {
    const { pi } = boot();
    pi.ui.notify = () => {
      throw new Error("notify exploded");
    };
    // An async hook that fails rejects; it must not take the session down.
    await expect(pi.emit("session_start")).resolves.toBeUndefined();
  });

  test("a corrupt shared ledger fails closed without crashing the session", async () => {
    const { repo, statePath } = makeRepoWithState({
      schema: 2,
      orchestrator_phase: "contract",
      brain: { awaiting_lanes: [] },
      lanes: {},
    });
    writeFileSync(statePath, "{broken", "utf8");
    const { pi, brain } = boot({ cwd: repo });

    await expect(pi.emit("session_start")).resolves.toBeUndefined();
    expect(brain.getState().orchestrator_phase).toBe("yield_and_guard");
    expect(brain.getState().blocked_reason).toContain("recovery");
    expect(pi.calls.notifications.some((n) => /unreadable|recovery/i.test(n.message))).toBe(true);
    expect(pi.calls.messages).toHaveLength(0);
  });

  test("a stall threshold produces a warning and a steer", async () => {
    // A real lane on disk, parked, whose pane never reports a state change.
    const { repo } = makeRepoWithState({
      lanes: { "1-1": { lane: "1-1", pane_id: "w3:p5" } },
    });
    const { pi, brain } = boot({ cwd: repo });
    pi.setPane("w3:p5", { pane_id: "w3:p5", agent_status: "working", state_change_seq: 7 });
    await pi.emit("session_start");
    brain.setState({
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["1-1"] },
    });

    for (let i = 0; i < 11; i += 1) brain.tick();

    expect(pi.calls.messages.some((m) => m.text.includes("has reported no state change"))).toBe(
      true,
    );
    expect(pi.calls.messages.some((m) => m.text.includes("1-1"))).toBe(true);
  });

  test("a moving lane is not reported as stalled", async () => {
    const { repo } = makeRepoWithState({
      lanes: { "1-1": { lane: "1-1", pane_id: "w3:p5" } },
    });
    const { pi, brain } = boot({ cwd: repo });
    pi.setPane("w3:p5", { pane_id: "w3:p5", agent_status: "working", state_change_seq: 1 });
    await pi.emit("session_start");
    brain.setState({
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["1-1"] },
    });

    for (let i = 0; i < 15; i += 1) {
      // The lane reports a new sequence every poll.
      pi.setPane("w3:p5", {
        pane_id: "w3:p5",
        agent_status: "working",
        state_change_seq: i + 2,
      });
      brain.tick();
    }
    expect(pi.calls.messages.some((m) => m.text.includes("has reported no state change"))).toBe(
      false,
    );
  });

  test("a persisted heartbeat survives restart and suppresses a false stall", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["1-1"], notifications_seen: 0 },
      lanes: {
        "1-1": {
          lane: "1-1",
          pane_id: "w3:p5",
          status: "working",
          current_stage: "Stage 4 Verifying on live-host",
          last_heartbeat: Date.now(),
        },
      },
    });
    const { pi, brain } = boot({ cwd: repo });
    pi.setPane("w3:p5", { pane_id: "w3:p5", agent_status: "working", state_change_seq: 1 });
    await pi.emit("session_start");
    expect(pi.calls.statuses.at(-1)).toEqual({ key: "dstate", value: "s4@live-host" });

    for (let i = 0; i < 15; i += 1) brain.tick();
    expect(pi.calls.messages.some((m) => m.text.includes("has reported no state change"))).toBe(
      false,
    );
  });

  test("a lane with an active Gate D semantic watchdog lease is not reported as stalled", async () => {
    const { repo } = makeRepoWithState({
      lanes: {
        "1-1": {
          lane: "1-1",
          pane_id: "w3:p5",
          watchdog_lease_until_unix_ms: Date.now() + 600_000,
        },
      },
    });
    const { pi, brain } = boot({ cwd: repo });
    pi.setPane("w3:p5", { pane_id: "w3:p5", agent_status: "working", state_change_seq: 1 });
    await pi.emit("session_start");
    brain.setState({
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["1-1"] },
    });

    for (let i = 0; i < 15; i += 1) {
      brain.tick();
    }
    expect(pi.calls.messages.some((m) => m.text.includes("has reported no state change"))).toBe(
      false,
    );
  });

  test("no stall warning while the orchestrator is not parked", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    brain.setState({ orchestrator_phase: "contract", brain: { awaiting_lanes: [] } });
    for (let i = 0; i < 10; i += 1) {
      pi.calls.intervals[0].fn();
    }
    expect(pi.calls.notifications.some((n) => n.message.includes("parked without"))).toBe(false);
  });

  test("a parked todo reminder is UI-only when native blocked mutation is unavailable", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["1-1"], notifications_seen: 0 },
      lanes: { "1-1": { lane: "1-1", pane_id: "w3:p5", status: "working" } },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");
    const before = pi.calls.messages.length;
    await pi.emit("todo_reminder");
    expect(pi.calls.messages).toHaveLength(before);
    expect(
      pi.calls.notifications.some((n) => n.message.includes("blocked status is NOT VERIFIED")),
    ).toBe(true);
  });

  test("timers are cleared on shutdown", async () => {
    const { pi } = boot();
    await pi.emit("session_start");
    const before = pi.calls.intervals.length;
    expect(before).toBeGreaterThan(0);
    await pi.emit("session_shutdown");
    expect(pi.calls.clearedTimers).toBe(before);
  });

  test("no raw timer is ever constructed", async () => {
    const source = require("node:fs").readFileSync(
      new URL("../agent/omp/extensions/dispatch-omp/index.ts", import.meta.url),
      "utf8",
    );
    const rawTimers = source.match(/(?<!ctx\.)(?<!eventCtx\.)(?<!pi\.)(?<![\w.])setInterval\s*\(/g) ?? [];
    expect(rawTimers).toEqual([]);
    expect(source).not.toMatch(/[^.\w]setTimeout\s*\(/);
  });
});

// --------------------------------------------------------------------------
// Subagent session isolation
// --------------------------------------------------------------------------

describe("subagent isolation", () => {
  test("subagent sessions never attach the loop", async () => {
    const { pi } = boot();
    await pi.emit("session_start", {}, { agent: { kind: "sub", name: "explore", depth: 0 } });
    expect(pi.calls.messages).toHaveLength(0);
    expect(pi.calls.intervals).toHaveLength(0);
  });

  test("depth is not used as an identity test", async () => {
    // A /tan clone is a subagent at depth 0, so depth alone would misclassify.
    const shallow = boot();
    await shallow.pi.emit("session_start", {}, { agent: { kind: "sub", name: "sub", depth: 0 } });
    expect(shallow.pi.calls.messages).toHaveLength(0);

    const root = boot();
    await root.pi.emit("session_start", {}, { agent: { kind: "main", name: "main", depth: 0 } });
    expect(root.pi.calls.messages).toHaveLength(0);
    expect(root.pi.calls.intervals.length).toBeGreaterThan(0);
  });

  test("a headless session does not attach", async () => {
    const { pi } = boot({ hasUI: false });
    await pi.emit("session_start");
    expect(pi.calls.messages).toHaveLength(0);
  });

  test("the park guard stays silent when not parked", async () => {
    const { pi } = boot();
    await pi.emit("session_start");
    await pi.emit("todo_reminder");
    // Not parked, so the extension must not intercept the host reminder.
    expect(pi.calls.messages).toHaveLength(0);
    expect(pi.calls.notifications).toHaveLength(0);
  });
});

// --------------------------------------------------------------------------
// Orthogonality and portability
// --------------------------------------------------------------------------

describe("decoupling", () => {
  test("the Herdr lifecycle adapter is read-only", async () => {
    const source = require("node:fs").readFileSync(
      new URL("../agent/omp/extensions/dispatch-omp/ledger.ts", import.meta.url),
      "utf8",
    );
    expect(source).toContain('["agent", "get", String(paneId)]');
    expect(source).not.toContain("report_metadata");
    expect(source).not.toContain("report-agent");
    expect(source).not.toContain('"agent", "prompt"');
  });

  test("the label is set once and identifies the extension", async () => {
    const { pi } = boot();
    await pi.emit("session_start");
    expect(pi.calls.labels).toEqual(["Dispatch Brain Loop"]);
  });

  test("no repository path is hardcoded", async () => {
    const source = require("node:fs").readFileSync(new URL("../agent/omp/extensions/dispatch-omp/index.ts", import.meta.url), "utf8");
    expect(source).not.toMatch(/Users\//);
    expect(source).not.toMatch(/work\/config\/mac-bootstrap/);
  });
});

describe("real Herdr lifecycle adapter", () => {
  test("known, absent, and query failure are distinct", () => {
    const known = lookupHerdrAgent("w3:pB", () => ({
      status: 0,
      stdout: JSON.stringify({
        result: { agent: { pane_id: "w3:pB", agent_status: "working", state_change_seq: 7 } },
      }),
      stderr: "",
    }));
    expect(known).toEqual({
      status: "known",
      info: { pane_id: "w3:pB", agent_status: "working", state_change_seq: 7 },
    });

    const absent = lookupHerdrAgent("w3:pZ", () => ({
      status: 1,
      stdout: JSON.stringify({
        error: { code: "agent_not_found", message: "agent target w3:pZ not found" },
      }),
      stderr: "",
    }));
    expect(absent.status).toBe("absent");

    const unknown = lookupHerdrAgent("w3:pB", () => ({
      status: 1,
      stdout: "{not-json",
      stderr: "socket unavailable",
    }));
    expect(unknown.status).toBe("unknown");
  });

  test("cold start keeps a claim when lifecycle lookup is unknown", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-x",
      orchestrator_phase: "yield_and_guard",
      brain: { awaiting_lanes: ["1-1"], notifications_seen: 0 },
      lanes: {
        "1-1": {
          lane: "1-1",
          pane_id: "w3:p5",
          status: "working",
          worktree: "/tmp/wt",
          branch: "feat/x",
        },
      },
    });
    const { pi, brain } = boot({
      cwd: repo,
      lookupPane: () => ({ status: "unknown", reason: "Herdr socket unavailable" }),
    });
    await pi.emit("session_start");

    expect(brain.getColdStart().live).toHaveLength(0);
    expect(brain.getColdStart().orphaned).toHaveLength(0);
    expect(brain.getColdStart().unknown).toHaveLength(1);
    expect(pi.calls.notifications.some((n) => n.message.includes("claims remain held"))).toBe(true);
  });
});

describe("state path resolution", () => {
  test("anchors on the git common dir so worktrees share one brain", async () => {
    const exec = () => ({ status: 0, stdout: "/repo/.git\n" });
    expect(resolveStatePath("/repo", exec)).toBe("/repo/.git/dispatch/ORCHESTRATOR_STATE.json");
  });

  test("falls back outside a repository", async () => {
    const exec = () => ({ status: 128, stdout: "" });
    expect(resolveStatePath("/tmp/x", exec)).toBe("/tmp/x/.dispatch/ORCHESTRATOR_STATE.json");
  });

  test("falls back when git throws", async () => {
    const exec = () => {
      throw new Error("git missing");
    };
    expect(resolveStatePath("/tmp/y", exec)).toBe("/tmp/y/.dispatch/ORCHESTRATOR_STATE.json");
  });
});

describe("routing config", () => {
  test("defaults apply when no config directory is given", async () => {
    expect(loadRouting(null)).toBe(DEFAULT_ROUTING);
  });

  test("a missing config file falls back to defaults", async () => {
    expect(loadRouting("/nonexistent-dir-xyz")).toBe(DEFAULT_ROUTING);
  });
});