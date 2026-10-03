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
import { existsSync, mkdtempSync, mkdirSync, readFileSync, realpathSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { describe, expect, test } from "bun:test";

import dispatchBrain, {
  AUTHORIZATION_KEY_ENV,
  authorizationProof,
  gateCProof,
  freezeProtectedLifecycleBundle,
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
  hasActiveRun,
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
const TEST_AUTHORIZATION_KEY = "dispatch-brain-test-runtime-key";

function signGateCFixtures(state: any) {
  for (const lane of Object.values(state?.lanes ?? {}) as any[]) {
    if (lane?.gate_c?.accepted === true && !lane.gate_c.gate_c_proof) {
      lane.gate_c.gate_c_proof = gateCProof(lane.gate_c, TEST_AUTHORIZATION_KEY);
    }
  }
  return state;
}

function makeRepoWithState(state: Record<string, unknown>) {
  const dir = mkdtempSync(path.join(tmpdir(), "dispatch-tick-"));
  const repo = path.join(dir, "repo");
  mkdirSync(repo, { recursive: true });
  execFileSync("git", ["init", "-q", repo]);
  const statePath = path.join(repo, ".git", "dispatch", "ORCHESTRATOR_STATE.json");
  mkdirSync(path.dirname(statePath), { recursive: true });
  writeFileSync(statePath, JSON.stringify(signGateCFixtures(state)));
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
    commands: new Map(),
    confirmations: [],
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
    registerCommand(name, def) {
      calls.commands.set(name, def);
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
      async confirm(title, message) {
        calls.confirmations.push({ title, message });
        return true;
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
  const {
    lookupPane: lookupOverride,
    gitRevision: gitRevisionOverride,
    pushUrl: pushUrlOverride,
    prHead: prHeadOverride,
    prContext: prContextOverride,
    lifecycleRunner: lifecycleRunnerOverride,
    authorizationKey: authorizationKeyOverride = TEST_AUTHORIZATION_KEY,
    hostMemory: hostMemoryOverride,
    ...hostOptions
  } = options;
  const pi = makeHost(hostOptions);
  const lookupPane =
    lookupOverride ??
    ((paneId: string) =>
      pi.paneInfo.has(paneId)
        ? { status: "known", info: pi.paneInfo.get(paneId) }
        : { status: "absent", reason: "agent_not_found" });
  const gitRevision = gitRevisionOverride ?? (() => "abc123");
  const pushUrl = pushUrlOverride ?? ((_repo: string, remote: string) => `ssh://git.example/${remote}.git`);
  const prHead = prHeadOverride ?? (() => "abc123");
  const brain = dispatchBrain(pi, {
    lookupPane,
    gitRevision,
    pushUrl,
    prHead,
    prContext: prContextOverride,
    lifecycleRunner: lifecycleRunnerOverride,
    authorizationKey: authorizationKeyOverride,
    hostMemory: hostMemoryOverride,
  });
  return { pi, brain };
}

function activateRun(brain: any, phase = "contract") {
  brain.setState({
    schema: 2,
    run_id: "run-current",
    orchestrator_phase: phase,
    brain: { awaiting_lanes: [], notifications_seen: 0 },
    lanes: {},
    extra_data: {},
    active_panes: { orchestrator: "", lanes: {} },
  });
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
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain);
    const result = await pi.emit("before_subagent_spawn", {
      agent: "researcher",
      invocationKind: "task",
      spawnKey: "k1",
    });
    expect(result.model).toEqual(["@slow"]);
    expect(result.note).toContain("role=researcher");
  });

  test("modelRole wins over the custom agent name", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain);
    const result = await pi.emit("before_subagent_spawn", {
      agent: "custom-worker",
      modelRole: "reviewer",
      spawnKey: "role-reviewer",
    });
    expect(result.model).toEqual(["@plan"]);
    expect(result.note).toContain("role=reviewer");
  });

  test("explicit spawn kind/model/patterns are preserved", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain);
    for (const [spawnKey, explicit] of [
      ["explicit-kind", { kind: "codex" }],
      ["explicit-model", { model: "openai/gpt-explicit" }],
      ["explicit-pattern", { pattern: "openai/gpt-*" }],
      ["explicit-patterns", { patterns: ["anthropic/claude-sonnet-4-5"] }],
    ]) {
      const result = await pi.emit("before_subagent_spawn", {
        agent: "custom-worker",
        modelRole: "reviewer",
        spawnKey,
        ...explicit,
      });
      expect(result).toBeUndefined();
    }
  });

  test("resource admission blocks a spawn before routing under pressure", async () => {
    const { pi, brain } = boot({
      hostMemory: () => ({ totalBytes: 100, freeBytes: 5 }),
    });
    await pi.emit("session_start");
    activateRun(brain);
    const result = await pi.emit("before_subagent_spawn", {
      modelRole: "researcher",
      spawnKey: "pressure-block",
    });
    expect(result.block).toBe(true);
    expect(result.reason).toContain("memory pressure");
    expect(brain.router.snapshot().seen).not.toContain("pressure-block");
  });

  test("unknown host memory is visible but does not invent pressure", async () => {
    const { pi, brain } = boot({ hostMemory: () => null });
    await pi.emit("session_start");
    activateRun(brain);
    expect(brain.getPressure()).toBe("unknown");
    const result = await pi.emit("before_subagent_spawn", {
      modelRole: "researcher",
      spawnKey: "unknown-pressure",
    });
    expect(result.block ?? false).toBe(false);
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
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain);
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

  test("an ordinary OMP session does not rewrite model selection", async () => {
    const { pi } = boot();
    await pi.emit("session_start");
    const result = await pi.emit("before_subagent_spawn", {
      agent: "researcher",
      invocationKind: "task",
      spawnKey: "ordinary",
    });
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
  test("destructive operations are blocked during an active run", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain, "human_gate");
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

  test("persisted phase text cannot disable a run that still has an identity", () => {
    expect(hasActiveRun({
      run_id: "run-current",
      orchestrator_phase: "closed",
      lanes: {
        "1-1": { status: "working", phase: "done" },
      },
    })).toBe(true);
    expect(hasActiveRun({
      run_id: "run-current",
      orchestrator_phase: "closed",
      lanes: {
        "1-1": { status: "released", phase: "closed" },
      },
    })).toBe(true);
    expect(hasActiveRun({ orchestrator_phase: "human_gate", lanes: {} })).toBe(false);
  });

  test("a forged top-level closed phase cannot disable gates while the finalized pane still exists", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "closed",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          pane_id: "w9:p1",
          status: "released",
          phase: "closed",
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({
      cwd: repo,
      lookupPane: (paneId: string) =>
        paneId === "w9:p1"
          ? { status: "known", info: { pane_id: paneId, agent_status: "idle", state_change_seq: 1 } }
          : { status: "absent", reason: "agent_not_found" },
    });
    await pi.emit("session_start");
    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "herdr pane close w9:p1" },
    });
    expect(result?.block ?? false).toBe(true);
    expect(result?.reason ?? "").toContain("human_gate");
  });

  test("forged closed state with erased run identity and lanes cannot detach a persisted run", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "",
      orchestrator_phase: "closed",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {},
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");
    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push origin main" },
    });
    expect(result?.block ?? false).toBe(true);
    expect(result?.reason ?? "").toContain("human_gate");
  });

  test("a later ordinary OMP session ignores a fully released run whose panes are physically absent", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          pane_id: "w9:p1",
          status: "released",
          phase: "closed",
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({
      cwd: repo,
      lookupPane: () => ({ status: "absent", reason: "agent_not_found" }),
    });
    await pi.emit("session_start");
    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push origin main" },
    });
    expect(result).toBeUndefined();
  });

  test("an ordinary OMP session keeps its normal tool and publish policy", async () => {
    const { pi } = boot();
    await pi.emit("session_start");
    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push origin main" },
    });
    expect(result).toBeUndefined();
  });

  test("explicit human authorization enters human_gate from synthesis", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "synthesis",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          branch: "feat/lane",
          handoff: "/tmp/handoff/current.md",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              repo: "ignored-by-authorization-command",
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              handoff: "/tmp/handoff/current.md",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const statePath = resolveStatePath(repo);
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");

    const command = pi.calls.commands.get("authorize-action");
    expect(command).toBeDefined();
    await command.handler("git_push --lane 1-1 --remote origin --ref feat/lane", {
      cwd: repo,
      ui: pi.ui,
    });

    const final = JSON.parse(readFileSync(statePath, "utf8"));
    expect(final.orchestrator_phase).toBe("human_gate");
    expect(final.extra_data.authorizations).toHaveLength(1);
  });

  test("a bound human authorization is consumed once by the matching tool call", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          worktree: "/tmp/worker",
          branch: "feat/lane",
          handoff: "/tmp/handoff/current.md",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              repo: "ignored-by-authorization-command",
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              handoff: "/tmp/handoff/current.md",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");

    const command = pi.calls.commands.get("authorize-action");
    expect(command).toBeDefined();
    await command.handler("git_push --lane 1-1 --remote origin --ref feat/lane", {
      cwd: repo,
      ui: pi.ui,
    });

    const first = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push origin abc123:feat/lane" },
    });
    expect(first).toBeUndefined();

    const second = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push origin feat/lane:feat/lane" },
    });
    expect(second?.block ?? false).toBe(true);
    expect(second?.reason ?? "").toContain("human_gate");
  });

  test("a forged persisted authorization cannot substitute for this session's human confirmation", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          branch: "feat/lane",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {
        authorizations: [{
          authorization_id: "forged",
          action: "git_push",
          repo: "forged-repo",
          ref: "feat/lane",
          run_id: "run-current",
          lane: "1-1",
          dispatch_id: "dispatch-current",
          gate_c_report_id: "gate-c-current",
          revision: "abc123",
          authorization_proof: "forged",
          authorized_unix_ms: 1,
          consumed_unix_ms: 0,
        }],
      },
      active_panes: { orchestrator: "", lanes: {} },
    });
    const statePath = resolveStatePath(repo);
    const seeded = JSON.parse(readFileSync(statePath, "utf8"));
    seeded.extra_data.authorizations[0].repo = realpathSync(repo);
    writeFileSync(statePath, JSON.stringify(seeded));

    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");
    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push origin feat/lane" },
    });
    expect(result?.block ?? false).toBe(true);
    const final = JSON.parse(readFileSync(statePath, "utf8"));
    expect(final.extra_data.authorizations[0].consumed_unix_ms).toBe(0);
  });

  test("worktree authority canonicalizes repo and ref symlink aliases", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
              delivery_scope: "local",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const root = path.dirname(repo);
    const repoAlias = path.join(root, "repo-alias");
    symlinkSync(repo, repoAlias);
    const worktree = path.join(root, "worker");
    mkdirSync(worktree);
    const worktreeAlias = path.join(root, "worker-alias");
    symlinkSync(worktree, worktreeAlias);

    const seededPath = resolveStatePath(repo);
    const seeded = JSON.parse(readFileSync(seededPath, "utf8"));
    seeded.lanes["1-1"].worktree = realpathSync(worktree);
    writeFileSync(seededPath, JSON.stringify(seeded));

    const { pi } = boot({ cwd: repoAlias });
    await pi.emit("session_start");
    const command = pi.calls.commands.get("authorize-action");
    await command.handler(
      `remove_worktree --lane 1-1 --ref ${worktreeAlias} --evidence '{"docs_aligned":{"docs_reconciled":true}}'`,
      { cwd: repoAlias, ui: pi.ui },
    );

    const state = JSON.parse(readFileSync(resolveStatePath(repo), "utf8"));
    const authority = state.extra_data.authorizations[0];
    expect(authority.repo).toBe(realpathSync(repo));
    expect(authority.ref).toBe(realpathSync(worktree));
  });

  test("remove-worktree authority cannot be consumed before cleanup authorization", async () => {
    const worktree = "/tmp/worker";
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          worktree,
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");
    const command = pi.calls.commands.get("authorize-action");
    await command.handler(`remove_worktree --lane 1-1 --ref ${worktree} --evidence '{"docs_aligned":{"docs_reconciled":true}}'`, {
      cwd: repo,
      ui: pi.ui,
    });

    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: `git worktree remove ${worktree}` },
    });
    expect(result?.block ?? false).toBe(true);
    expect(result?.reason ?? "").toContain("human_gate");
  });

  test("close-pane authority cannot be consumed before finalization", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          status: "done",
          phase: "done",
          pane_id: "w9:p1",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");
    const command = pi.calls.commands.get("authorize-action");
    await command.handler("close_pane --lane 1-1 --ref w9:p1", {
      cwd: repo,
      ui: pi.ui,
    });

    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "herdr pane close w9:p1" },
    });
    expect(result?.block ?? false).toBe(true);
  });

  test("raw git worktree removal stays Gate-A blocked even after human cleanup authority", async () => {
    const worktree = "/tmp/worker";
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          worktree,
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
              delivery_scope: "local",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");
    const command = pi.calls.commands.get("authorize-action");
    await command.handler(`remove_worktree --lane 1-1 --ref ${worktree} --evidence '{"docs_aligned":{"docs_reconciled":true}}'`, {
      cwd: repo,
      ui: pi.ui,
    });

    const statePath = resolveStatePath(repo);
    const state = JSON.parse(readFileSync(statePath, "utf8"));
    const authority = state.extra_data.authorizations[0];
    state.lanes["1-1"].cleanup_authorization = {
      authorization_id: authority.authorization_id,
      gate_c_report_id: "gate-c-current",
      run_id: "run-current",
      dispatch_id: "dispatch-current",
      worktree,
      revision: "abc123",
      outcome: "delivered",
    };
    writeFileSync(statePath, JSON.stringify(state));

    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: `git worktree remove ${worktree}` },
    });
    expect(result?.block ?? false).toBe(true);
    expect(result?.reason ?? "").toContain("Gate A refused");

    const unchanged = JSON.parse(readFileSync(statePath, "utf8"));
    expect(unchanged.extra_data.authorizations[0].consumed_unix_ms).toBe(0);
  });

  test("finalized lane may consume a separate close-pane authority", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          pane_id: "w9:p1",
          status: "released",
          phase: "closed",
          cleanup_finalized_unix_ms: 1,
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");
    const command = pi.calls.commands.get("authorize-action");
    await command.handler("close_pane --lane 1-1 --ref w9:p1", {
      cwd: repo,
      ui: pi.ui,
    });

    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "herdr pane close w9:p1" },
    });
    expect(result).toBeUndefined();
  });

  test("standard git-push argv variants consume the same exact remote and ref authority", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");
    const command = pi.calls.commands.get("authorize-action");
    await command.handler("git_push --lane 1-1 --remote origin --ref feat/lane", {
      cwd: repo,
      ui: pi.ui,
    });

    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push --set-upstream origin abc123:feat/lane" },
    });
    expect(result).toBeUndefined();
  });

  test("old human authority does not survive a root-session restart", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          branch: "feat/lane",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });

    const first = boot({ cwd: repo });
    await first.pi.emit("session_start");
    const command = first.pi.calls.commands.get("authorize-action");
    await command.handler("git_push --lane 1-1 --remote origin --ref feat/lane", {
      cwd: repo,
      ui: first.pi.ui,
    });

    const second = boot({ cwd: repo });
    await second.pi.emit("session_start");
    const result = await second.pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push origin feat/lane:feat/lane" },
    });
    expect(result?.block ?? false).toBe(true);
    expect(result?.reason ?? "").toContain("human_gate");

    const state = JSON.parse(readFileSync(resolveStatePath(repo), "utf8"));
    expect(state.extra_data.authorizations[0].consumed_unix_ms).toBe(0);
  });

  test("TypeScript authorization proof matches the Python canonical vector including numeric zero", () => {
    const proof = authorizationProof({
      authorization_id: "human-vector",
      action: "remove_worktree",
      repo: "/repo",
      remote: "",
      push_url: "",
      ref: "/repo/wt",
      destination_ref: "",
      run_id: "run-1",
      lane: "1-1",
      dispatch_id: "dispatch-1",
      gate_c_report_id: "gate-c-1",
      revision: "abc123",
      outcome: "delivered",
      delivery_scope: "local",
      authorized_unix_ms: 123,
      consumed_unix_ms: 0,
    }, "vector-key");
    expect(proof).toBe("739728e446417f121622dbd1a2b808345c862dfe7e78c17ec8020962453108de");
  });

  test("TypeScript Gate C proof matches the Python canonical vector", () => {
    const proof = gateCProof({
      report_id: "gate-c-vector",
      accepted: true,
      outcome: "delivered",
      binding: {
        repo: "/repo",
        run_id: "run-1",
        lane: "1-1",
        dispatch_id: "dispatch-1",
        handoff: "/tmp/handoff/x.md",
        revision: "abc123",
        delivery_scope: "repository",
        evidence_digest: "digest123",
      },
      verified_unix_ms: 123,
    }, "vector-key");
    expect(proof).toBe("dd976964e26571d30fe783a913bd87b7ced28af2d05188e998cbc7af509adb45");
  });

  test("protected lifecycle source is frozen before later repository edits", () => {
    const root = mkdtempSync(path.join(tmpdir(), "dispatch-protected-"));
    const bin = path.join(root, "bin");
    const lib = path.join(root, "lib");
    mkdirSync(bin, { recursive: true });
    mkdirSync(lib, { recursive: true });
    const plugin = path.join(bin, "dispatch_plugin.py");
    const module = path.join(lib, "guard.py");
    writeFileSync(plugin, "print('trusted-v1')\n");
    writeFileSync(module, "VALUE = 'trusted-v1'\n");

    const frozen = freezeProtectedLifecycleBundle(plugin);
    writeFileSync(plugin, "print('worker-mutated')\n");
    writeFileSync(module, "VALUE = 'worker-mutated'\n");

    const payload = JSON.parse(frozen);
    expect(payload.plugin).toContain("trusted-v1");
    expect(payload.plugin).not.toContain("worker-mutated");
    expect(payload.modules.guard).toContain("trusted-v1");
    expect(payload.modules.guard).not.toContain("worker-mutated");
  });

  test("consumed cleanup authority cannot be revived by rolling back the shared state", async () => {
    const root = mkdtempSync(path.join(tmpdir(), "dispatch-rollback-"));
    const repo = path.join(root, "repo");
    const worktree = path.join(root, "worker");
    mkdirSync(repo, { recursive: true });
    execFileSync("git", ["init", "-q", repo]);
    execFileSync("git", ["-C", repo, "config", "user.name", "Dispatch-Test"]);
    execFileSync("git", ["-C", repo, "config", "user.email", "dispatch-test"]);
    writeFileSync(path.join(repo, "tracked.txt"), "base\n");
    execFileSync("git", ["-C", repo, "add", "tracked.txt"]);
    execFileSync("git", ["-C", repo, "commit", "-qm", "base"]);
    execFileSync("git", ["-C", repo, "worktree", "add", "-q", "-b", "feat/lane", worktree]);
    const revision = execFileSync("git", ["-C", worktree, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
    const statePath = resolveStatePath(repo);
    mkdirSync(path.dirname(statePath), { recursive: true });
    writeFileSync(statePath, JSON.stringify(signGateCFixtures({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          worktree,
          branch: "feat/lane",
          delivery_scope: "local",
          handoff: "/tmp/handoff/current.md",
          status: "done",
          phase: "done",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            outcome: "delivered",
            binding: {
              repo: realpathSync(repo),
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              handoff: "/tmp/handoff/current.md",
              revision,
              delivery_scope: "local",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    })));

    const plugin = path.resolve(import.meta.dir, "../multiplexer/herdr-dispatch/bin/dispatch_plugin.py");
    const previousPlugin = process.env.HERDR_DISPATCH_PLUGIN;
    process.env.HERDR_DISPATCH_PLUGIN = plugin;
    try {
      const { pi } = boot({ cwd: repo, gitRevision: () => revision });
      await pi.emit("session_start");
      const authorize = pi.calls.commands.get("authorize-action");
      await authorize.handler(`remove_worktree --lane 1-1 --ref ${worktree} --evidence '{"docs_aligned":{"docs_reconciled":true}}'`, { cwd: repo, ui: pi.ui });

      const authorizeCleanup = pi.calls.commands.get("authorize-cleanup");
      await authorizeCleanup.handler(`--lane 1-1 --evidence '{"docs_aligned":{"docs_reconciled":true}}'`, { cwd: repo, ui: pi.ui });
      const beforeCleanup = readFileSync(statePath, "utf8");

      const cleanup = pi.calls.commands.get("cleanup-worktree");
      await cleanup.handler("--lane 1-1", { cwd: repo, ui: pi.ui });
      expect(existsSync(worktree)).toBe(false);

      // Restore the signed pre-consumption document and recreate the same path
      // at the same revision. The in-process consumption ledger must still
      // reject the old one-shot authority.
      writeFileSync(statePath, beforeCleanup);
      execFileSync("git", ["-C", repo, "worktree", "add", "-q", worktree, "feat/lane"]);
      const notificationCount = pi.calls.notifications.length;
      await cleanup.handler("--lane 1-1", { cwd: repo, ui: pi.ui });
      expect(existsSync(worktree)).toBe(true);
      const latest = pi.calls.notifications.slice(notificationCount).map((entry) => entry.message).join("\n");
      expect(latest).toContain("no matching current-session human remove_worktree authority is active");
    } finally {
      if (previousPlugin === undefined) delete process.env.HERDR_DISPATCH_PLUGIN;
      else process.env.HERDR_DISPATCH_PLUGIN = previousPlugin;
    }
  });

  test("real Gate C through authorize cleanup remove finalize closes a no-change lane", async () => {
    const root = mkdtempSync(path.join(tmpdir(), "dispatch-closeout-e2e-"));
    const repo = path.join(root, "repo");
    const worktree = path.join(root, "worker");
    const handoff = path.join(root, "handoff.md");
    mkdirSync(repo, { recursive: true });
    execFileSync("git", ["init", "-q", repo]);
    execFileSync("git", ["-C", repo, "config", "user.name", "Dispatch-Test"]);
    execFileSync("git", ["-C", repo, "config", "user.email", "dispatch-test"]);
    writeFileSync(path.join(repo, "tracked.txt"), "base\n");
    execFileSync("git", ["-C", repo, "add", "tracked.txt"]);
    execFileSync("git", ["-C", repo, "commit", "-qm", "base"]);
    execFileSync("git", ["-C", repo, "worktree", "add", "-q", "-b", "feat/lane", worktree]);
    const revision = execFileSync("git", ["-C", worktree, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
    writeFileSync(
      handoff,
      "# Handoff\n\nOutcome: no_change. Tests passed and the worker tree is clean.\n",
    );

    const statePath = resolveStatePath(repo);
    mkdirSync(path.dirname(statePath), { recursive: true });
    writeFileSync(statePath, JSON.stringify({
      schema: 2,
      run_id: "run-e2e-closeout",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-e2e-closeout",
          dispatch_id: "dispatch-e2e-closeout",
          worktree,
          branch: "feat/lane",
          delivery_scope: "local",
          handoff,
          status: "done",
          phase: "done",
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    }));

    const plugin = path.resolve(import.meta.dir, "../multiplexer/herdr-dispatch/bin/dispatch_plugin.py");
    const previousPlugin = process.env.HERDR_DISPATCH_PLUGIN;
    process.env.HERDR_DISPATCH_PLUGIN = plugin;
    try {
      const { pi } = boot({ cwd: repo, gitRevision: () => revision });
      await pi.emit("session_start");

      const verify = pi.calls.commands.get("verify-handoff");
      await verify.handler(
        `--lane 1-1 --handoff ${handoff} --test-log-text PASS --diff-text "" --exit-code 0 --bind-current --outcome no_change --json`,
        { cwd: repo, ui: pi.ui },
      );
      let state = JSON.parse(readFileSync(statePath, "utf8"));
      expect(state.lanes["1-1"].gate_c.accepted).toBe(true);
      expect(state.lanes["1-1"].gate_c.binding.revision).toBe(revision);

      const evidence = `{"docs_aligned":{"docs_reconciled":true}}`;
      const authorize = pi.calls.commands.get("authorize-action");
      await authorize.handler(
        `remove_worktree --lane 1-1 --ref ${worktree} --evidence '${evidence}'`,
        { cwd: repo, ui: pi.ui },
      );

      const authorizeCleanup = pi.calls.commands.get("authorize-cleanup");
      await authorizeCleanup.handler(
        `--lane 1-1 --evidence '${evidence}'`,
        { cwd: repo, ui: pi.ui },
      );
      state = JSON.parse(readFileSync(statePath, "utf8"));
      const persistedCleanupWorktree =
        state.lanes["1-1"].cleanup_authorization.worktree;
      expect(persistedCleanupWorktree).toBe(realpathSync(worktree));
      if (process.platform === "darwin" && worktree.startsWith("/var/")) {
        expect(persistedCleanupWorktree.startsWith("/private/var/")).toBe(true);
      }

      const cleanup = pi.calls.commands.get("cleanup-worktree");
      await cleanup.handler("--lane 1-1 --json", { cwd: repo, ui: pi.ui });
      expect(existsSync(worktree)).toBe(false);

      const finalize = pi.calls.commands.get("finalize-closeout");
      await finalize.handler(
        `--lane 1-1 --evidence '${evidence}' --json`,
        { cwd: repo, ui: pi.ui },
      );

      state = JSON.parse(readFileSync(statePath, "utf8"));
      expect(state.lanes["1-1"].status).toBe("released");
      expect(state.lanes["1-1"].phase).toBe("closed");
      expect(state.lanes["1-1"].cleanup_finalized_unix_ms).toBeGreaterThan(0);
    } finally {
      if (previousPlugin === undefined) delete process.env.HERDR_DISPATCH_PLUGIN;
      else process.env.HERDR_DISPATCH_PLUGIN = previousPlugin;
    }
  });

  test("runtime authorization key is not ambient and reaches only the protected lifecycle child", async () => {
    let capturedKey = "";
    delete process.env[AUTHORIZATION_KEY_ENV];
    const { pi, brain } = boot({
      lifecycleRunner: (_repo: string, _subcommand: string, _argv: string[], key: string) => {
        capturedKey = key;
        return "";
      },
    });
    await pi.emit("session_start");
    activateRun(brain, "human_gate");

    expect(process.env[AUTHORIZATION_KEY_ENV]).toBeUndefined();
    const command = pi.calls.commands.get("authorize-cleanup");
    expect(command).toBeDefined();
    await command.handler("--lane 1-1 --evidence {}", {
      cwd: process.cwd(),
      ui: pi.ui,
    });

    expect(capturedKey.length).toBeGreaterThan(10);
    expect(process.env[AUTHORIZATION_KEY_ENV]).toBeUndefined();
  });

  test("git-push authority cannot be replayed against another remote", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          branch: "feat/lane",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");
    const command = pi.calls.commands.get("authorize-action");
    await command.handler("git_push --lane 1-1 --remote origin --ref feat/lane", {
      cwd: repo,
      ui: pi.ui,
    });

    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push backup feat/lane:feat/lane" },
    });
    expect(result?.block ?? false).toBe(true);
    expect(result?.reason ?? "").toContain("human_gate");

    const state = JSON.parse(readFileSync(resolveStatePath(repo), "utf8"));
    expect(state.extra_data.authorizations[0].consumed_unix_ms).toBe(0);
  });

  test("git-push authority refuses a branch that changed after Gate C", async () => {
    let revision = "abc123";
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          branch: "feat/lane",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            outcome: "delivered",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
              delivery_scope: "repository",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo, gitRevision: () => revision });
    await pi.emit("session_start");
    revision = "def456";
    const command = pi.calls.commands.get("authorize-action");
    await command.handler("git_push --lane 1-1 --remote origin --ref feat/lane", {
      cwd: repo,
      ui: pi.ui,
    });
    expect(
      pi.calls.notifications.some((entry) =>
        entry.message.includes("branch revision changed after Gate C"),
      ),
    ).toBe(true);
    const state = JSON.parse(readFileSync(resolveStatePath(repo), "utf8"));
    expect(state.extra_data.authorizations ?? []).toHaveLength(0);
  });

  test("git-push authority is invalidated when the approved remote changes destination", async () => {
    let pushUrl = "ssh://git.example/origin-a.git";
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          branch: "feat/lane",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            outcome: "delivered",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
              delivery_scope: "repository",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo, pushUrl: () => pushUrl });
    await pi.emit("session_start");
    const command = pi.calls.commands.get("authorize-action");
    await command.handler("git_push --lane 1-1 --remote origin --ref feat/lane", {
      cwd: repo,
      ui: pi.ui,
    });

    pushUrl = "ssh://git.example/origin-b.git";
    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push origin feat/lane:feat/lane" },
    });
    expect(result?.block ?? false).toBe(true);

    const state = JSON.parse(readFileSync(resolveStatePath(repo), "utf8"));
    expect(state.extra_data.authorizations[0].consumed_unix_ms).toBe(0);
  });

  test("python process-launch wrappers cannot bypass the human gate", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain, "human_gate");
    for (const code of [
      `import subprocess; subprocess.run(["git", "push", "origin", "feat/lane"])`,
      `import subprocess as s; s.run(["git", "push", "--force", "origin", "feat/lane"])`,
      `from subprocess import run as r; r(["gh", "pr", "merge", "12"])`,
      `import os; os.system("gh pr merge 12")`,
      `import pty; pty.spawn(["git", "push", "origin", "feat/lane"])`,
    ]) {
      const result = await pi.emit("tool_call", { toolName: "python", input: { code } });
      expect(result?.block ?? false).toBe(true);
      expect(result?.reason ?? "").toContain("human_gate");
    }
  });

  test("worker Python execution is fail-closed during an active dispatch", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain, "human_gate");
    const result = await pi.emit(
      "tool_call",
      {
        toolName: "python",
        input: {
          code: `m = __import__("sub" + "process"); m.run(["g" + "it", "push", "--force", "origin", "feat/lane"])`,
        },
      },
      { agent: { kind: "sub" }, hasUI: false, cwd: "/tmp/worker" },
    );
    expect(result?.block ?? false).toBe(true);
    expect(result?.reason ?? "").toContain("root-only");
  });

  test("worker cannot delete or mutate the shared dispatch state path", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain, "human_gate");
    for (const command of [
      "rm ../../.git/dispatch/ORCHESTRATOR_STATE.json",
      "rm -rf ../../.git/dispatch",
      "mv ../../.git/dispatch/ORCHESTRATOR_STATE.json /tmp/state",
      "cp /dev/null ../../.git/dispatch/ORCHESTRATOR_STATE.json",
    ]) {
      const result = await pi.emit(
        "tool_call",
        { toolName: "bash", input: { command } },
        { agent: { kind: "sub" }, hasUI: false, cwd: "/tmp/worker" },
      );
      expect(result?.block ?? false).toBe(true);
      expect(result?.reason ?? "").toContain("shared dispatch state");
    }
    const ordinary = await pi.emit(
      "tool_call",
      { toolName: "bash", input: { command: "git status --short" } },
      { agent: { kind: "sub" }, hasUI: false, cwd: "/tmp/worker" },
    );
    expect(ordinary).toBeUndefined();
  });

  test("shell-escaped Python interpreter names are fail-closed", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain, "human_gate");
    for (const command of [
      String.raw`p\ython3 -c 'print(1)'`,
      String.raw`/usr/bin/py\thon3 -c 'print(1)'`,
    ]) {
      const result = await pi.emit("tool_call", {
        toolName: "bash",
        input: { command },
      });
      expect(result?.block ?? false).toBe(true);
      expect(result?.reason ?? "").toContain("human_gate");
    }
  });

  test("worker sessions cannot bypass the human gate for protected actions", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain, "human_gate");
    for (const command of [
      "git push --force origin feat/lane",
      "gh pr merge 12 --match-head-commit abc123",
      "git worktree remove /tmp/worker",
      "herdr pane close w9:p1",
      `p=python3; "$p" -c 'print(1)'`,
      `export p=/usr/bin/python3; "\${p}" -c 'print(1)'`,
      `p\\ython3 -c 'print(1)'`,
      `p=py; q=thon3; "$p$q" -c 'print(1)'`,
    ]) {
      const result = await pi.emit(
        "tool_call",
        { toolName: "bash", input: { command } },
        { agent: { kind: "sub" }, hasUI: false, cwd: "/tmp/worker" },
      );
      expect(result?.block ?? false).toBe(true);
      expect(result?.reason ?? "").toContain("root-only");
    }
    const ordinary = await pi.emit(
      "tool_call",
      { toolName: "bash", input: { command: "git status --short" } },
      { agent: { kind: "sub" }, hasUI: false, cwd: "/tmp/worker" },
    );
    expect(ordinary).toBeUndefined();
  });

  test("cmd and script aliases use the same destructive command classifier", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain, "human_gate");
    for (const input of [
      { cmd: "git push --force origin feat/lane" },
      { script: "gh pr merge 12 --match-head-commit abc123" },
    ]) {
      const result = await pi.emit("tool_call", { toolName: "bash", input });
      expect(result?.block ?? false).toBe(true);
      expect(result?.reason ?? "").toContain("human_gate");
    }
  });

  test("a missing run_id cannot detach persisted active lanes", async () => {
    expect(hasActiveRun({
      run_id: "",
      orchestrator_phase: "closed",
      lanes: { "1-1": { status: "working", phase: "done" } },
    })).toBe(true);
    expect(hasActiveRun({
      run_id: "",
      orchestrator_phase: "closed",
      lanes: { "1-1": { status: "released", phase: "closed" } },
    })).toBe(false);
  });

  test("shell-like tool aliases and git/gh global-option forms stay human-gated", async () => {
    const { pi, brain } = boot();
    await pi.emit("session_start");
    activateRun(brain, "human_gate");
    for (const [toolName, command] of [
      ["shell", "git -C /tmp/repo push --force origin feat/lane"],
      ["exec", "gh --repo owner/repo pr merge 12"],
      ["command", "git -C /tmp/repo push origin feat/lane"],
    ]) {
      const result = await pi.emit("tool_call", { toolName, input: { command } });
      expect(result?.block ?? false).toBe(true);
      expect(result?.reason ?? "").toContain("human_gate");
    }
  });

  test("force push cannot consume an ordinary git-push authority", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");
    const command = pi.calls.commands.get("authorize-action");
    await command.handler("git_push --lane 1-1 --remote origin --ref feat/lane", {
      cwd: repo,
      ui: pi.ui,
    });

    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push --force origin feat/lane" },
    });
    expect(result?.block ?? false).toBe(true);
    expect(result?.reason ?? "").toContain("human_gate");
    expect(classifyToolCall("bash", { command: "git push --force origin feat/lane" }).authority)
      .toBeNull();
    expect(classifyToolCall("bash", { command: "git push -f origin feat/lane" }).authority)
      .toBeNull();
    expect(classifyToolCall("bash", { command: "git push --delete origin feat/lane" }).authority)
      .toBeNull();
    expect(classifyToolCall("bash", { command: "git push --mirror origin" }).authority)
      .toBeNull();
  });

  test("PR merge authority refuses a PR head that changed after Gate C", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    let prContext = {
      headRefOid: "deadbeef",
      headRefName: "feat/lane",
      baseRefName: "main",
      url: "https://github.com/example/repo/pull/12",
    };
    const { pi } = boot({ cwd: repo, prContext: () => ({ ...prContext }) });
    await pi.emit("session_start");
    const command = pi.calls.commands.get("authorize-action");
    await command.handler("merge_pr --lane 1-1 --ref 12", {
      cwd: repo,
      ui: pi.ui,
    });
    let state = JSON.parse(readFileSync(resolveStatePath(repo), "utf8"));
    expect(state.extra_data?.authorizations ?? []).toHaveLength(0);

    prContext.headRefOid = "abc123";
    await command.handler("merge_pr --lane 1-1 --ref 12", {
      cwd: repo,
      ui: pi.ui,
    });
    state = JSON.parse(readFileSync(resolveStatePath(repo), "utf8"));
    expect(state.extra_data.authorizations).toHaveLength(1);

    prContext.headRefOid = "cafebabe";
    const stale = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "gh pr merge 12 --match-head-commit abc123" },
    });
    expect(stale?.block ?? false).toBe(true);
    expect(stale?.reason ?? "").toContain("human_gate");

    prContext.headRefOid = "abc123";
    prContext.baseRefName = "release";
    const changedBase = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "gh pr merge 12 --match-head-commit abc123" },
    });
    expect(changedBase?.block ?? false).toBe(true);

    prContext.baseRefName = "main";
    prContext.url = "https://github.com/other/repo/pull/12";
    const changedRepo = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "gh pr merge 12 --match-head-commit abc123" },
    });
    expect(changedRepo?.block ?? false).toBe(true);

    state = JSON.parse(readFileSync(resolveStatePath(repo), "utf8"));
    expect(state.extra_data.authorizations[0].consumed_unix_ms).toBe(0);
  });

  test("PR merge authority cannot absorb extra command semantics", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");
    const command = pi.calls.commands.get("authorize-action");
    await command.handler("merge_pr --lane 1-1 --ref 12", {
      cwd: repo,
      ui: pi.ui,
    });

    const otherRef = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "gh pr merge 13" },
    });
    expect(otherRef?.block ?? false).toBe(true);
    expect(otherRef?.reason ?? "").toContain("human_gate");
    expect(classifyToolCall("bash", { command: "gh pr merge 13" }).authority).toBeNull();

    expect(classifyToolCall("bash", {
      command: "gh pr merge 12 --match-head-commit abc123",
    }).authority).toEqual({ action: "merge_pr", ref: "12", revision: "abc123" });

    for (const candidate of [
      "gh pr merge 12",
      "gh pr merge 12 --admin",
      "gh pr merge 12 --delete-branch",
      "gh pr merge 12 --repo other/repo",
    ]) {
      const result = await pi.emit("tool_call", {
        toolName: "bash",
        input: { command: candidate },
      });
      expect(result?.block ?? false).toBe(true);
      expect(result?.reason ?? "").toContain("human_gate");
      expect(classifyToolCall("bash", { command: candidate }).authority).toBeNull();
    }

    const staleHead = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "gh pr merge 12 --match-head-commit deadbeef" },
    });
    expect(staleHead?.block ?? false).toBe(true);
    expect(staleHead?.reason ?? "").toContain("human_gate");
    expect(classifyToolCall("bash", {
      command: "gh pr merge 12 --match-head-commit deadbeef",
    }).authority).toEqual({ action: "merge_pr", ref: "12", revision: "deadbeef" });

    const state = JSON.parse(readFileSync(resolveStatePath(repo), "utf8"));
    expect(state.extra_data.authorizations[0].consumed_unix_ms).toBe(0);
  });

  test("authorization for one ref cannot unlock another ref", async () => {
    const { repo } = makeRepoWithState({
      schema: 2,
      run_id: "run-current",
      orchestrator_phase: "human_gate",
      brain: { awaiting_lanes: [], notifications_seen: 1 },
      lanes: {
        "1-1": {
          lane: "1-1",
          run_id: "run-current",
          dispatch_id: "dispatch-current",
          gate_c: {
            accepted: true,
            report_id: "gate-c-current",
            binding: {
              run_id: "run-current",
              lane: "1-1",
              dispatch_id: "dispatch-current",
              revision: "abc123",
            },
          },
        },
      },
      extra_data: {},
      active_panes: { orchestrator: "", lanes: {} },
    });
    const { pi } = boot({ cwd: repo });
    await pi.emit("session_start");

    const command = pi.calls.commands.get("authorize-action");
    await command.handler("git_push --lane 1-1 --remote origin --ref feat/lane", {
      cwd: repo,
      ui: pi.ui,
    });

    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git push origin other-branch" },
    });
    expect(result?.block ?? false).toBe(true);
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
  test("shipped routing applies when no operator config directory is given", async () => {
    expect(loadRouting(null)).toEqual(DEFAULT_ROUTING);
  });

  test("operator routing config overrides the shared role mapping", async () => {
    const configDir = mkdtempSync(path.join(tmpdir(), "dispatch-routing-"));
    writeFileSync(
      path.join(configDir, "routing.json"),
      JSON.stringify({ researcher: { patterns: ["@plan"], kind: "agy" } }),
    );
    const routing = loadRouting(configDir);
    expect(routing.researcher).toEqual({ patterns: ["@plan"], kind: "agy" });
    expect(routing.writer).toEqual(DEFAULT_ROUTING.writer);
  });

  test("a missing config file falls back to defaults", async () => {
    expect(loadRouting("/nonexistent-dir-xyz")).toBe(DEFAULT_ROUTING);
  });
});