/**
 * Tests for Gate A: the PreToolUse reflex gate (Issue #133).
 *
 * Run with:  bun test agent/omp/extensions/dispatch-omp/
 *
 * The Python half (`orchestrator_guard.py`) is the authority; this is the
 * in-process fast path that runs before it. Two things are therefore tested
 * here: that the rules behave, and — the part that is easy to forget — that the
 * two halves still agree, because a silent drift between them is a hole in the
 * seam rather than a failing test somewhere else.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, test } from "bun:test";

import dispatchBrain, {
  BUSINESS_CODE_TOOLS,
  GateAVerdict,
  PROBE_TOOLS,
  THRESHOLD_ILLEGAL_PROBE,
  THRESHOLD_ROLE_BOUNDARY,
  TOOL_WHITELIST,
  isBusinessCodePath,
  isIsolatedWorktree,
  isManagementCall,
  isProbeCommand,
  isRootDestructive,
  isRootDestructiveCall,
  isWhitelistedPath,
  reflexGate,
} from "../agent/omp/extensions/dispatch-omp/index.ts";

const PARKED = { orchestrator_phase: "yield_and_guard", brain: { awaiting_lanes: ["1-4"] } };
const SYNTHESIS = { orchestrator_phase: "synthesis", brain: { awaiting_lanes: ["1-4"] } };
const HOME = "/srv/home/tester";

/** A tool event as the host hands it over. */
function call(toolName, input = {}, extra = {}) {
  return { toolName, input, cwd: "/srv/home/tester/work/config/mac-bootstrap", ...extra };
}

function judge(state, event) {
  return reflexGate(state, event, { home: HOME });
}

// --------------------------------------------------------------------------
// Layer 1 — the fast local bypass
// --------------------------------------------------------------------------

describe("Gate A whitelist bypass", () => {
  test("management tools need no target at all", () => {
    for (const tool of TOOL_WHITELIST) {
      const verdict = judge(PARKED, call(tool));
      expect(verdict.allowed).toBe(true);
      expect(verdict.verdict).toBe(GateAVerdict.WHITELISTED);
    }
  });

  test("the run's own state and handoffs are readable while parked", () => {
    for (const target of [
      "/repo/.git/dispatch/ORCHESTRATOR_STATE.json",
      "/srv/home/tester/Documents/handoffs/1-5-handoff.md",
      "/repo/.dispatch_task_gate_a.md",
    ]) {
      const verdict = judge(PARKED, call("read_file", { path: target }));
      expect(verdict.allowed).toBe(true);
      expect(verdict.verdict).toBe(GateAVerdict.WHITELISTED);
    }
  });

  test("a tilde path is expanded before it is compared", () => {
    expect(isWhitelistedPath("~/Documents/handoffs/x.md", HOME)).toBe(true);
  });

  test("the bypass costs no model call", () => {
    // A delegate that throws proves the bypass short-circuits before it.
    const verdict = reflexGate(PARKED, call("todo"), {
      home: HOME,
      semantic: () => {
        throw new Error("whitelist bypass reached the semantic layer");
      },
    });
    expect(verdict.allowed).toBe(true);
  });

  test("a management command cannot smuggle lane code past the gate", () => {
    const verdict = judge(
      PARKED,
      call("bash", { command: "cat handoff.md && cat .worktrees/1-4/src/app.py" }),
    );
    expect(verdict.allowed).toBe(false);
  });

  test("passing the command in either field is the same call", () => {
    // Otherwise the bypass would be buyable by choosing the other argument.
    expect(isManagementCall("bash", { command: "python3 bin/dispatch_plugin.py status" }, HOME)).toBe(
      true,
    );
    expect(isManagementCall("bash", { target: "python3 bin/dispatch_plugin.py status" }, HOME)).toBe(
      true,
    );
  });
});

// --------------------------------------------------------------------------
// Layer 2 — mechanical facts
// --------------------------------------------------------------------------

describe("Gate A mechanical interception", () => {
  test("business-code reads are refused while parked", () => {
    for (const tool of BUSINESS_CODE_TOOLS) {
      const verdict = judge(PARKED, call(tool, { path: ".worktrees/1-4/src/app.py" }));
      expect(verdict.allowed).toBe(false);
      expect(verdict.verdict).toBe(GateAVerdict.REFUSE_CHILD_CODE);
    }
  });

  test("reading source outside the park is legitimate reconciliation", () => {
    const verdict = judge(SYNTHESIS, call("read_file", { path: "src/parser.py" }));
    expect(verdict.allowed).toBe(true);
  });

  test("a probe is refused in every phase", () => {
    for (const state of [PARKED, SYNTHESIS]) {
      const verdict = judge(state, call("bash", { command: "git status" }));
      expect(verdict.allowed).toBe(false);
      expect(verdict.verdict).toBe(GateAVerdict.REFUSE_PROBE);
    }
  });

  test("a parked orchestrator may still read its own docs", () => {
    expect(judge(PARKED, call("read_file", { path: "CONTEXT.md" })).allowed).toBe(true);
  });
});

// --------------------------------------------------------------------------
// Root checkout protection — the incident, codefied
// --------------------------------------------------------------------------

describe("root checkout protection", () => {
  const ROOT = "/srv/home/tester/work/config/mac-bootstrap";

  test.each([
    "git reset --hard",
    "git reset --hard origin/main",
    "git clean -fd",
    "git clean -fdx",
    "git checkout -- .",
    "rm -rf src/",
    "git push --force origin main",
    "git branch -D feat/gate-a",
  ])("%s is refused in a canonical root checkout", (command) => {
    for (const state of [PARKED, SYNTHESIS, { orchestrator_phase: "contract" }]) {
      const verdict = reflexGate(state, call("bash", { command }, { cwd: ROOT }), { home: HOME });
      expect(verdict.allowed).toBe(false);
      expect(verdict.verdict).toBe(GateAVerdict.REFUSE_ROOT_DESTRUCTIVE);
    }
  });

  test("a submodule root is a canonical root too", () => {
    const verdict = reflexGate(
      PARKED,
      call("bash", { command: "git reset --hard" }, { cwd: `${ROOT}/template` }),
      { home: HOME },
    );
    expect(verdict.allowed).toBe(false);
  });

  test("a lane worktree may reset its own scratch tree", () => {
    const verdict = reflexGate(
      PARKED,
      call(
        "bash",
        { command: "git reset --hard" },
        { cwd: "/srv/home/tester/.herdr/worktrees/mac-bootstrap/feat-gate-a" },
      ),
      { home: HOME },
    );
    expect(verdict.allowed).toBe(true);
  });

  test(".worktrees/ is an isolation root as well", () => {
    expect(isIsolatedWorktree(`${ROOT}/.worktrees/feat-auth`)).toBe(true);
  });

  test("protection is about destroying the tree, not about reading it", () => {
    for (const command of ["git status", "git diff --stat", "git log --oneline -3"]) {
      expect(isRootDestructive(command)).toBe(false);
    }
  });

  test("a soft or mixed reset is not destructive", () => {
    // `--soft` and `--mixed` keep the working tree; refusing them would be a
    // gate that trains people to route around it.
    expect(isRootDestructive("git reset --soft HEAD~1")).toBe(false);
    expect(isRootDestructive("git reset --mixed HEAD~1")).toBe(false);
  });

  test("the destructive flags are not mistaken for probe verbs", () => {
    // `\bfd\b` also matches the `-fd` in `git clean -fd`; a probe pattern that
    // fired there would refuse the very command the isolation boundary permits.
    const verdict = reflexGate(
      PARKED,
      call("bash", { command: "git clean -fd" }, { cwd: `${ROOT}/.worktrees/feat-auth` }),
      { home: HOME },
    );
    expect(verdict.allowed).toBe(true);
  });

  test("a parent traversal cannot borrow a worktree's name", () => {
    // `<root>/.worktrees/../<root>` is the root checkout wearing a worktree's
    // name. Resolving the path before the segment check is what makes the
    // boundary mean anything.
    for (const cwd of [
      `${ROOT}/.worktrees/../config/mac-bootstrap`,
      "/srv/home/tester/.herdr/worktrees/../../work/config/mac-bootstrap",
    ]) {
      expect(isIsolatedWorktree(cwd)).toBe(false);
      const verdict = reflexGate(PARKED, call("bash", { command: "git reset --hard" }, { cwd }), {
        home: HOME,
      });
      expect(verdict.allowed).toBe(false);
      expect(verdict.verdict).toBe(GateAVerdict.REFUSE_ROOT_DESTRUCTIVE);
    }
  });

  test("the traversal check still permits a genuine worktree", () => {
    expect(isIsolatedWorktree(`${ROOT}/.worktrees/feat-auth`)).toBe(true);
    expect(isIsolatedWorktree("/nonexistent/.worktrees/feat-auth")).toBe(true);
    expect(isIsolatedWorktree("/nonexistent/repo")).toBe(false);
  });
});

// --------------------------------------------------------------------------
// Layer composition — where a per-layer test is not enough
// --------------------------------------------------------------------------

describe("Gate A layers compose in the right order", () => {
  const ROOT = "/srv/home/tester/work/config/mac-bootstrap";

  test.each([
    ["git reset --hard", ""],
    ["", "git reset --hard"],
    // Both set: `command || target` picks one, so the *other* must still be
    // judged. Without that, putting the destructive text in `target` while
    // `command` holds something innocuous is a free pass.
    ["python3 -m pip list", "git reset --hard"],
    ["git reset --hard", "python3 -m pip list"],
    ["cat /srv/home/tester/Documents/handoffs/plan.md && git reset --hard", ""],
    // One argument carrying both a marker and the destruction: the marker must
    // not vouch for the rest of its own line.
    ["python3 -m pip list", "cat /srv/home/tester/Documents/handoffs/x.md && git reset --hard"],
    ["", "python3 bin/dispatch_plugin.py status && git clean -fd"],
    ["dispatch_plugin.py status; git reset --hard origin/main", ""],
  ])("a management read cannot buy %j / %j", (command, target) => {
    // The bypass must not sit ahead of the mechanical rules, or a leading
    // legitimate path would carry a trailing `git reset --hard` straight
    // through. Each layer is individually correct; only the order is not.
    const verdict = reflexGate(PARKED, call("bash", { command, target }, { cwd: ROOT }), {
      home: HOME,
    });
    expect(verdict.allowed).toBe(false);
    expect(verdict.verdict).toBe(GateAVerdict.REFUSE_ROOT_DESTRUCTIVE);
  });

  test("a management read cannot buy a lane code read either", () => {
    const verdict = judge(
      PARKED,
      call("bash", {
        command:
          "cat /srv/home/tester/Documents/handoffs/x.md && cat .worktrees/1-4/src/app.py",
      }),
    );
    expect(verdict.allowed).toBe(false);
    expect(verdict.verdict).toBe(GateAVerdict.REFUSE_CHILD_CODE);
  });

  test("a tool this gate has never heard of is still judged", () => {
    // A destructive command is a fact about the command. Gating the rule on a
    // known tool class would mean a renamed tool silences it.
    const verdict = reflexGate(
      PARKED,
      { toolName: "some_future_shell", input: { command: "git reset --hard" }, cwd: ROOT },
      { home: HOME },
    );
    expect(verdict.allowed).toBe(false);
    expect(verdict.verdict).toBe(GateAVerdict.REFUSE_ROOT_DESTRUCTIVE);
  });

  test("a whitelisted handoff carrying a source suffix is not business code", () => {
    // The marker check runs before the lowercasing, or `ORCHESTRATOR_STATE.json`
    // could never match and every such file would read as code.
    expect(isBusinessCodePath("/srv/home/tester/Documents/handoffs/notes.py", HOME)).toBe(false);
    expect(isBusinessCodePath("/repo/.git/dispatch/ORCHESTRATOR_STATE.json", HOME)).toBe(false);
    expect(isBusinessCodePath("src/parser.py", HOME)).toBe(true);
  });

  test.each([
    "/repo/.dispatch/../src/app.py",
    "/srv/home/tester/Documents/handoffs/../../../src/app.py",
    "/repo/.dispatch/../../.worktrees/1-4/src/app.py",
  ])("a whitelist marker cannot be walked out of with %j", (target) => {
    // A marker is a substring, so `..` walks straight out of the directory it
    // named. The whitelist is a bypass; a bypass you can walk out of is not one.
    const verdict = judge(PARKED, call("read_file", { path: target }));
    expect(verdict.allowed).toBe(false);
    expect(verdict.verdict).not.toBe(GateAVerdict.WHITELISTED);
  });

  test("the traversal check keeps the bypass's legitimate cases", () => {
    for (const target of [
      "/repo/.dispatch/TASK.md",
      "/srv/home/tester/.herdr/worktrees/mac-bootstrap/feat-a/.dispatch/TASK.md",
    ]) {
      expect(isManagementCall("read_file", { target }, HOME)).toBe(true);
    }
  });

  test("neither argument may vouch for the other", () => {
    // The disqualifiers used to live only on the command branch, so a marker in
    // `target` short-circuited the `or` and the command went unchecked.
    const verdict = judge(
      PARKED,
      call("bash", {
        target: "/srv/home/tester/Documents/handoffs/x.md",
        command: "cat .worktrees/1-4/src/app.py",
      }),
    );
    expect(verdict.allowed).toBe(false);
    expect(verdict.verdict).toBe(GateAVerdict.REFUSE_CHILD_CODE);
  });
});

describe("Gate A judges the command's target, not only the cwd", () => {
  const ROOT = "/srv/home/tester/work/config/mac-bootstrap";
  const LANE = "/srv/home/tester/.herdr/worktrees/mac-bootstrap/feat-a";

  test.each([
    `git -C ${ROOT} clean -fdx`,
    `git -C ${ROOT} reset --hard`,
    `git --git-dir ${ROOT}/.git clean -fd`,
    `git -C${ROOT} checkout .`,
  ])("%j is refused even from a lane worktree", (command) => {
    // A worktree cwd plus a `git -C <root>` is a root checkout reached through
    // the back door, and it is the shape a lane produces by accident.
    for (const cwd of [LANE, ""]) {
      const verdict = reflexGate(PARKED, call("bash", { command }, { cwd }), { home: HOME });
      expect(verdict.allowed).toBe(false);
      expect(verdict.verdict).toBe(GateAVerdict.REFUSE_ROOT_DESTRUCTIVE);
    }
  });

  test.each(["git switch --discard-changes", "rm --recursive --force src/", "git worktree remove .worktrees/1-4"])(
    "%j obeys the isolation boundary in both directions",
    (command) => {
      // Both the refusal in a root and the permission in a worktree are
      // asserted: a gate that refused everywhere would train people to route
      // around it, which is a failure that looks like success.
      for (const cwd of [ROOT, ""]) {
        const verdict = reflexGate(PARKED, call("bash", { command }, { cwd }), { home: HOME });
        expect(verdict.allowed).toBe(false);
        expect(verdict.verdict).toBe(GateAVerdict.REFUSE_ROOT_DESTRUCTIVE);
      }
      const inside = reflexGate(
        PARKED,
        call("bash", { command }, { cwd: `${ROOT}/.worktrees/feat-auth` }),
        { home: HOME },
      );
      expect(inside.allowed).toBe(true);
    },
  );

  test("a tool this gate has not heard of is still judged on shape", () => {
    // A whitelist of tool names has a failure mode with no off switch: rename
    // `read_file` to `read` and the rule silently stops applying.
    for (const toolName of ["read", "open_file", "fs_read", "some_future_reader", ""]) {
      const verdict = judge(PARKED, call(toolName, { path: ".worktrees/1-4/src/app.py" }));
      expect(verdict.allowed).toBe(false);
    }
    const shellish = judge(
      PARKED,
      { toolName: "some_future_shell", input: { command: "cat .worktrees/1-4/src/app.py" } },
    );
    expect(shellish.allowed).toBe(false);
    expect(shellish.verdict).toBe(GateAVerdict.REFUSE_CHILD_CODE);
    // The reason must name the lane worktree, not merely "a .py file": the two
    // rules refuse alike, and only one of them tells the orchestrator what it
    // actually reached for.
    expect(shellish.reason).toContain("lane worktree");
  });

  test.each(["read", "open_file", "fs_read", ""])(
    "%j reading ordinary source while parked is still business code",
    (toolName) => {
      // Deliberately *not* a lane worktree path, so the lane-code rule above
      // cannot be what refuses it. This isolates the generic source rule, and it
      // is the case a tool-name gate would let through.
      const verdict = judge(PARKED, call(toolName, { path: "src/parser.py" }));
      expect(verdict.allowed).toBe(false);
      expect(verdict.verdict).toBe(GateAVerdict.REFUSE_CHILD_CODE);
    },
  );

  test("the same read outside the park is allowed whatever the tool is called", () => {
    // Guards the other direction: reading source in synthesis is reconciliation,
    // and a gate that refuses it would be worse than no gate.
    for (const toolName of ["read_file", "read", ""]) {
      expect(judge(SYNTHESIS, call(toolName, { path: "src/parser.py" })).allowed).toBe(true);
    }
  });
});

// --------------------------------------------------------------------------
// Layer 3 — the delegated semantic layer
// --------------------------------------------------------------------------

describe("Gate A semantic layer", () => {
  test("a role boundary violation over the threshold blocks", () => {
    const verdict = reflexGate(PARKED, call("webfetch", { url: "https://x/1-4" }), {
      home: HOME,
      semantic: () => ({ pRoleBoundaryViolation: 0.71, pIllegalProbeWhileParked: 0.05 }),
    });
    expect(verdict.allowed).toBe(false);
    expect(verdict.verdict).toBe(GateAVerdict.REFUSE_SEMANTIC);
    expect(verdict.steer).toContain("child-work takeover");
  });

  test("an illegal probe while parked blocks", () => {
    const verdict = reflexGate(PARKED, call("shell", { command: "lane-status 1-4" }), {
      home: HOME,
      semantic: () => ({ pRoleBoundaryViolation: 0.1, pIllegalProbeWhileParked: 0.66 }),
    });
    expect(verdict.allowed).toBe(false);
  });

  test("below the threshold the call proceeds", () => {
    const verdict = reflexGate(PARKED, call("shell", { command: "date" }), {
      home: HOME,
      semantic: () => ({ pRoleBoundaryViolation: 0.2, pIllegalProbeWhileParked: 0.05 }),
    });
    expect(verdict.allowed).toBe(true);
  });

  test("a mechanical refusal never reaches the delegate", () => {
    // A fact does not get a second opinion from a model.
    const verdict = reflexGate(PARKED, call("read_file", { path: ".worktrees/1-4/src/a.py" }), {
      home: HOME,
      semantic: () => {
        throw new Error("mechanical refusal reached the semantic layer");
      },
    });
    expect(verdict.allowed).toBe(false);
  });

  test("no delegate means the mechanical layers still stand", () => {
    const verdict = judge(PARKED, call("read_file", { path: ".worktrees/1-4/src/a.py" }));
    expect(verdict.allowed).toBe(false);
  });
});

// --------------------------------------------------------------------------
// The steer, and the session it is injected into
// --------------------------------------------------------------------------

describe("Gate A corrective steer", () => {
  test("a refusal always carries a steer", () => {
    for (const event of [
      call("read_file", { path: ".worktrees/1-4/src/a.py" }),
      call("bash", { command: "git status" }),
      call("bash", { command: "git reset --hard" }),
    ]) {
      const verdict = judge(PARKED, event);
      expect(verdict.allowed).toBe(false);
      expect(verdict.steer.length).toBeGreaterThan(0);
    }
  });

  test("the steer names the lanes being awaited", () => {
    const verdict = judge(PARKED, call("read_file", { path: ".worktrees/1-4/src/a.py" }));
    expect(verdict.steer).toContain("1-4");
  });

  test("the root-checkout steer names the worktree remedy", () => {
    const verdict = judge(PARKED, call("bash", { command: "git reset --hard" }));
    expect(verdict.steer).toContain(".worktrees");
  });
});

describe("Gate A session wiring", () => {
  function makeHost({ agent = { kind: "main" }, hasUI = true, cwd = "/repo" } = {}) {
    const calls = { messages: [], notifications: [], intervals: [], clearedTimers: 0, labels: [] };
    const handlers = new Map();
    const host = {
      calls,
      handlers,
      on(name, fn) {
        handlers.set(name, fn);
        return host;
      },
      emit(name, event = {}, extra = {}) {
        const fn = handlers.get(name);
        if (!fn) return undefined;
        const ctx = {
          hasUI,
          cwd,
          agent,
          isIdle: () => true,
          ui: host.ui,
          setInterval: (fn2, ms) => calls.intervals.push({ fn: fn2, ms }),
          setTimeout: (fn2, ms) => calls.intervals.push({ fn: fn2, ms }),
          clearTimer: () => {},
          ...extra,
        };
        return fn(event, ctx);
      },
      ui: { notify: (message, level) => calls.notifications.push({ message, level }) },
      setLabel: (label) => calls.labels.push(label),
      sendUserMessage: (text, options) => calls.messages.push({ text, options }),
      herdrAgentInfo: () => null,
    };
    return host;
  }

  test("a parked business-code read is blocked and steered", async () => {
    const pi = makeHost();
    const brain = dispatchBrain(pi);
    await pi.emit("session_start", {});
    brain.setState(PARKED);

    const result = await pi.emit("tool_call", call("read_file", { path: ".worktrees/1-4/src/a.py" }));
    expect(result?.block).toBe(true);
    expect(result.reason).toContain("Gate A");
    expect(pi.calls.messages.at(-1).text).toContain("child-work takeover");
  });

  test("a root reset is blocked in the orchestrator's own session", async () => {
    // The cwd comes from the handler *context*, not the event — that is the shape
    // a real host produces, and it is the only thing that makes the isolation
    // boundary usable. Asserting the event shape instead would pass while
    // production never supplied a directory at all.
    const pi = makeHost({ cwd: "/srv/home/tester/work/config/mac-bootstrap" });
    const brain = dispatchBrain(pi);
    await pi.emit("session_start", {});
    brain.setState({ orchestrator_phase: "topology", brain: { awaiting_lanes: [] } });

    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git reset --hard origin/main" },
    });
    expect(result?.block).toBe(true);
    expect(result.reason).toContain("root checkout");
  });

  test("the same session inside a lane worktree may reset its own tree", async () => {
    // The other half of the same wiring. If the cwd were dropped, this would
    // over-block and the gate would be the thing people route around.
    const pi = makeHost({ cwd: "/srv/home/tester/repo/.worktrees/feat-auth" });
    const brain = dispatchBrain(pi);
    await pi.emit("session_start", {});
    brain.setState({ orchestrator_phase: "topology", brain: { awaiting_lanes: [] } });

    const result = await pi.emit("tool_call", {
      toolName: "bash",
      input: { command: "git reset --hard" },
    });
    expect(result).toBeUndefined();
  });

  test("a todo reminder is never blocked", async () => {
    const pi = makeHost();
    const brain = dispatchBrain(pi);
    await pi.emit("session_start", {});
    brain.setState(PARKED);
    expect(await pi.emit("tool_call", call("todo"))).toBeUndefined();
  });

  test("a subagent is exempt — it is the worker", async () => {
    const pi = makeHost({ agent: { kind: "sub" } });
    const brain = dispatchBrain(pi);
    await pi.emit("session_start", {});
    brain.setState(PARKED);

    // Blocking a lane's own tool calls would be the takeover in reverse.
    const result = await pi.emit("tool_call", call("read_file", { path: ".worktrees/1-4/src/a.py" }));
    expect(result).toBeUndefined();
  });

  test("the human gate still fires after Gate A allows a call", async () => {
    const pi = makeHost();
    const brain = dispatchBrain(pi);
    await pi.emit("session_start", {});
    brain.setState({ orchestrator_phase: "human_gate", brain: { awaiting_lanes: [] } });

    const result = await pi.emit("tool_call", call("bash", { command: "git push origin feat" }));
    expect(result?.block).toBe(true);
    expect(result.reason).toContain("human authorisation");
  });

  test("a host that refuses the steer still gets the block", async () => {
    // The steer is best effort by design — a refused injection must not unblock
    // the call. Asserting the block survives is what stops a future edit from
    // turning a delivery failure into a bypass.
    const pi = makeHost();
    pi.sendUserMessage = () => {
      throw new Error("injection refused by the host");
    };
    const brain = dispatchBrain(pi);
    await pi.emit("session_start", {});
    brain.setState(PARKED);

    const result = await pi.emit("tool_call", call("read_file", { path: ".worktrees/1-4/src/a.py" }));
    expect(result?.block).toBe(true);
  });

  test("a host without the steer API is still blocked", async () => {
    const pi = makeHost();
    pi.sendUserMessage = undefined;
    const brain = dispatchBrain(pi);
    await pi.emit("session_start", {});
    brain.setState(PARKED);

    const result = await pi.emit("tool_call", call("read_file", { path: ".worktrees/1-4/src/a.py" }));
    expect(result?.block).toBe(true);
  });

  test("a command both gates names both reasons", async () => {
    // `rm -rf /` in a root checkout is irreversible *and* aimed at the wrong
    // tree. Reporting only the first gate to fire would teach the model that the
    // other one does not apply.
    const pi = makeHost();
    const brain = dispatchBrain(pi);
    await pi.emit("session_start", {});
    brain.setState(PARKED);

    const result = await pi.emit("tool_call", call("bash", { command: "rm -rf /" }));
    expect(result?.block).toBe(true);
    expect(result.reason).toContain("human_gate");
    expect(result.reason).toContain("Gate A");
  });
});

// --------------------------------------------------------------------------
// Drift between the two halves
// --------------------------------------------------------------------------

const repoRoot = path.join(import.meta.dir, "..");

/**
 * Commands that must classify identically on both sides of the seam.
 *
 * Written once and used by both the TS expectation and the Python run, so the two
 * lists cannot drift apart — which would make a drift test pass while testing
 * nothing. Every case is one where a plausible simplification would disagree:
 * `--soft` and `--mixed` resets keep the tree, `-fd` is not the `fd` finder,
 * `-f` alone is not `rm -rf`, and `-n` is a dry run.
 */
const DESTRUCTIVE_CORPUS = [
  "git reset --hard",
  "git reset --hard origin/main",
  "git reset HEAD~1",
  "git reset --soft HEAD~1",
  "git reset --mixed HEAD~1",
  "git clean -fd",
  "git clean -fdx",
  "git clean -n",
  "git checkout -- .",
  "git checkout .",
  "git checkout feat/a",
  "git restore .",
  "git restore --staged .",
  "git stash drop",
  "git stash list",
  "git push --force origin main",
  "git push origin main",
  "rm -rf src/",
  "rm -f tmp.txt",
  "git branch -D feat/gate-a",
  "git branch -d feat/gate-a",
  "make check",
  "python3 -m pip list",
  "date",
  "",
  // Global flags between `git` and the subcommand: the same destruction with a
  // detour, which a pattern demanding `git clean` adjacently does not see.
  "git -C /srv/orch/repo clean -fdx",
  "git -C/srv/orch/repo checkout .",
  "git --git-dir /srv/orch/repo/.git clean -fd",
  "git switch --discard-changes",
  "git switch feat/a",
  "rm --recursive --force src/",
  "rm -f tmp.txt",
  "rm -r src",
  "git worktree remove .worktrees/1-4",
  "git worktree list",
  "git reset --soft HEAD~1",
  "git commit -m 'x'",
];

const PROBE_CORPUS = [
  "git status",
  "git diff --stat",
  "git log --oneline -3",
  "cat src/app.py",
  "ls -la",
  "ls -la .worktrees/1-4",
  "git clean -fd",
  "git commit -m 'x'",
  "python3 -m pip list",
  "python3 bin/dispatch_plugin.py status",
  "make check",
  "echo hello",
  "",
  "git -C /srv/orch/repo status",
  "rm --recursive --force src/",
  "git switch --discard-changes",
];

/**
 * Paths that must read the same on both sides.
 *
 * The two cases that matter most are the ones that already went wrong once: a
 * whitelisted path that also ends in a source suffix (a handoff called
 * `notes.py` is management, not business code), and a case-sensitive marker.
 * The `~/` entries are what catch a home-expansion implemented on one side only.
 */
const PATH_CORPUS = [
  "src/parser.py",
  "CONTEXT.md",
  ".git/dispatch/ORCHESTRATOR_STATE.json",
  "/repo/.git/dispatch/ORCHESTRATOR_STATE.json",
  "/repo/.git/dispatch/CHECKPOINT.json",
  "~/Documents/handoffs/1-5-handoff.md",
  "~/Documents/handoffs/notes.py",
  "/srv/home/tester/Documents/handoffs/notes.py",
  "~/Documents/handoffs/",
  ".dispatch_task_gate_a.md",
  "/repo/.dispatch/TASK.md",
  "script.sh",
  "Makefile",
  "",
  // The cases that already went wrong once: a marker walked out of with `..`,
  // and a cased marker compared against a lowercased path.
  "/srv/orch/repo/.dispatch/../src/app.py",
  "/srv/orch/repo/.dispatch/../../.worktrees/1-4/src/app.py",
  "/srv/home/tester/Documents/handoffs/../../../src/app.py",
  "ORCHESTRATOR_STATE.json",
  "~/Documents/handoffs/notes.py",
];

/** Working directories that must resolve to the same isolation answer. */
const CWD_CORPUS = [
  "/srv/home/tester/work/config/mac-bootstrap",
  "/srv/home/tester/work/config/mac-bootstrap/.worktrees/feat-auth",
  "/srv/home/tester/.herdr/worktrees/mac-bootstrap/feat-gate-a",
  "/srv/home/tester/work/config/mac-bootstrap/.worktrees/../config/mac-bootstrap",
  "/srv/home/tester/.herdr/worktrees/../../work/config/mac-bootstrap",
  "/nonexistent/.worktrees/feat-auth",
  "/nonexistent/repo",
  "",
  "/srv/orch/work/config/mac-bootstrap/.worktrees/../config/mac-bootstrap",
  "/srv/orch/work/config/mac-bootstrap/.worktrees/feat-auth/sub/dir",
  "/srv/orch/worktrees/feat-a",
];

/**
 * (command, cwd) pairs for the isolation conjunction.
 *
 * Both halves of the conjunction are exercised on purpose: a command naming a
 * root from a worktree cwd, and a command naming a worktree from a root cwd. A
 * test that only ever pairs a command with a matching cwd would pass against an
 * implementation that ignored `-C` entirely.
 */
const ROOT = "/srv/home/tester/work/config/mac-bootstrap";
const LANE = "/srv/home/tester/.herdr/worktrees/mac-bootstrap/feat-a";

const ROOT_CALL_CORPUS = [
  ["git reset --hard", ROOT],
  ["git reset --hard", LANE],
  ["git reset --hard", ""],
  [`git -C ${ROOT} clean -fdx`, LANE],
  [`git -C ${ROOT} clean -fdx`, ROOT],
  [`git -C ${ROOT} reset --hard`, ""],
  [`git -C${ROOT} checkout .`, LANE],
  [`git --git-dir ${ROOT}/.git clean -fd`, LANE],
  [`git -C ${ROOT}/.worktrees/feat-auth clean -fd`, LANE],
  ["git switch --discard-changes", ROOT],
  ["git switch --discard-changes", LANE],
  ["rm --recursive --force src/", ROOT],
  ["rm --recursive --force src/", LANE],
  ["git worktree remove .worktrees/1-4", ROOT],
  ["git worktree remove .worktrees/1-4", LANE],
  ["rm -rf src/", LANE],
  ["git status", ROOT],
  ["git status", LANE],
  ["python3 -m pip list", ""],
  ["", ""],
];

/**
 * (tool, target, command) triples for the management predicate.
 *
 * Every case has a marker somewhere and something disqualifying somewhere else.
 * That combination is the whole point: a disqualifier checked only on the branch
 * that found the marker is a disqualifier that never runs.
 */
const MANAGEMENT_CORPUS = [
  ["todo", "", ""],
  ["read_file", ".git/dispatch/ORCHESTRATOR_STATE.json", ""],
  ["read_file", "CONTEXT.md", ""],
  ["bash", "", "python3 bin/dispatch_plugin.py status"],
  ["bash", "python3 bin/dispatch_plugin.py status", ""],
  // A marker in target, something disqualifying in command.
  ["bash", "/srv/home/tester/Documents/handoffs/x.md", "cat .worktrees/1-4/src/app.py"],
  ["read_file", "/repo/.dispatch/TASK.md", "cat .worktrees/1-4/src/app.py"],
  ["bash", "/srv/home/tester/Documents/handoffs/x.md", "git reset --hard"],
  // ...and the reverse.
  ["bash", "", "cat /srv/home/tester/Documents/handoffs/x.md && git reset --hard"],
  ["bash", "cat /srv/home/tester/Documents/handoffs/x.md && git reset --hard", ""],
  // Marker walked out of with `..`.
  ["read_file", "/repo/.dispatch/../src/app.py", ""],
  ["read_file", "~/Documents/handoffs/../../../src/app.py", ""],
  ["bash", "", "cat /repo/.dispatch/../src/app.py"],
  // A source file under a marker is still management.
  ["read_file", "/srv/home/tester/Documents/handoffs/notes.py", ""],
  ["", "", ""],
];

/**
 * Classify every corpus with the real Python module.
 *
 * A drift test is only worth anything if it compares against the code that
 * actually runs, so this executes `orchestrator_guard.py` rather than
 * re-parsing it. The corpus goes in over stdin, so no shell quoting can corrupt
 * a case.
 */
let pythonGatePromise = null;
function loadPythonGate() {
  if (!pythonGatePromise) {
    pythonGatePromise = (async () => {
      const { spawnSync } = await import("node:child_process");
      const gatePath = path.join(
        repoRoot,
        "multiplexer",
        "herdr-dispatch",
        "lib",
        "orchestrator_guard.py",
      );
      const script = `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("gate_a_drift", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
# Registered before exec: a dataclass with a string annotation resolves its own
# module through sys.modules, so an unregistered module fails on 3.9.
sys.modules["gate_a_drift"] = mod
spec.loader.exec_module(mod)
corpus = json.loads(sys.stdin.read())
home = corpus["home"]
print(json.dumps({
    "destructive": [mod.is_root_destructive(c) for c in corpus["destructive"]],
    "probe": [mod.is_probe_command(c) for c in corpus["probe"]],
    "business_code": [mod.is_business_code_path(p) for p in corpus["paths"]],
    "isolated": [mod.is_isolated_worktree(c) for c in corpus["cwds"]],
    "root_destructive_call": [
        mod.is_root_destructive_call(c[0], cwd=c[1]) for c in corpus["root_calls"]
    ],
    "management": [
        mod.is_management_call(c[0], target=c[1], command=c[2]) for c in corpus["mgmt"]
    ],
}))
`;
      const proc = spawnSync("python3", ["-c", script, gatePath], {
        input: JSON.stringify({
          destructive: DESTRUCTIVE_CORPUS,
          probe: PROBE_CORPUS,
          paths: PATH_CORPUS,
          cwds: CWD_CORPUS,
          root_calls: ROOT_CALL_CORPUS,
          mgmt: MANAGEMENT_CORPUS,
          home: HOME,
        }),
        encoding: "utf8",
      });
      if (proc.status !== 0) {
        throw new Error(`python gate failed to load: ${proc.stderr}`);
      }
      return JSON.parse(proc.stdout);
    })();
  }
  return pythonGatePromise;
}

describe("Gate A halves agree", () => {
  const repoRoot = path.join(import.meta.dir, "..");
  const python = readFileSync(
    path.join(repoRoot, "multiplexer", "herdr-dispatch", "lib", "orchestrator_guard.py"),
    "utf8",
  );
  const reflexSource = readFileSync(
    path.join(repoRoot, "agent", "omp", "extensions", "dispatch-omp", "reflex.ts"),
    "utf8",
  );

  /**
   * Pull a string list out of a Python literal.
   *
   * Tolerates the type annotation, an optional `frozenset(...)` wrapper, and both
   * the one-line and multi-line spellings — so adding an annotation or reflowing
   * a literal does not quietly turn a drift test into a no-op.
   */
  function pythonStrings(name) {
    const match = new RegExp(
      `${name}[^=]*=\\s*(?:frozenset\\(\\s*)?(\\{[\\s\\S]*?\\}|\\([^)]*\\))`,
      "m",
    ).exec(python);
    expect(match, `${name} not found in orchestrator_guard.py`).toBeTruthy();
    return [...match[1].matchAll(/["']([^"']+)["']/g)].map((m) => m[1]).sort();
  }

  /** The same, out of a TS `NAME = Object.freeze([...])` literal. */
  function tsStrings(name) {
    const match = new RegExp(`${name} = Object\\.freeze\\(\\[([\\s\\S]*?)\\]\\)`).exec(reflexSource);
    expect(match, `${name} not found in reflex.ts`).toBeTruthy();
    return [...match[1].matchAll(/["']([^"']+)["']/g)].map((m) => m[1]).sort();
  }

  test("the tool classes are the same set on both sides", () => {
    expect(pythonStrings("BUSINESS_CODE_TOOLS")).toEqual([...BUSINESS_CODE_TOOLS].sort());
    expect(pythonStrings("PROBE_TOOLS")).toEqual([...PROBE_TOOLS].sort());
    expect(pythonStrings("TOOL_WHITELIST")).toEqual([...TOOL_WHITELIST].sort());
  });

  test("the whitelist path markers are the same set", () => {
    expect(pythonStrings("WHITELIST_PATH_MARKERS")).toEqual(
      tsStrings("WHITELIST_PATH_MARKERS"),
    );
  });

  test("the isolation roots are the same set", () => {
    expect(pythonStrings("_ISOLATED_ROOTS")).toEqual(tsStrings("ISOLATED_ROOTS"));
  });

  test("the thresholds are the issue's 0.40 on both sides", () => {
    expect(THRESHOLD_ROLE_BOUNDARY).toBe(0.4);
    expect(THRESHOLD_ILLEGAL_PROBE).toBe(0.4);
    expect(python).toContain("THRESHOLD_ROLE_BOUNDARY = 0.40");
    expect(python).toContain("THRESHOLD_ILLEGAL_PROBE = 0.40");
  });

  test("both sides classify the same destructive commands", async () => {
    // Regex bodies cannot be compared textually across two languages, so the
    // invariant tested is behavioural: one corpus, two implementations, identical
    // answers. A rule added to one side only shows up here as a disagreement.
    const { destructive } = await loadPythonGate();
    const fromTs = DESTRUCTIVE_CORPUS.map(isRootDestructive);
    expect(fromTs).toEqual(destructive);
  });

  test("both sides classify the same probe commands", async () => {
    const { probe } = await loadPythonGate();
    expect(PROBE_CORPUS.map(isProbeCommand)).toEqual(probe);
  });

  test("both sides read the same paths as business code", async () => {
    // This is the class of asymmetry the constant-set tests cannot see: the
    // marker list can match on both sides while one of them lowercases the path
    // first and can therefore never match a cased marker.
    const { business_code } = await loadPythonGate();
    expect(PATH_CORPUS.map((p) => isBusinessCodePath(p, HOME))).toEqual(business_code);
  });

  test("both sides resolve the same working directories to isolation", async () => {
    const { isolated } = await loadPythonGate();
    expect(CWD_CORPUS.map(isIsolatedWorktree)).toEqual(isolated);
  });

  test("both sides reach the same verdict on the isolation conjunction", async () => {
    // The conjunction over cwd *and* the directories the command names. Testing
    // `isRootDestructive` alone misses it entirely, since that function has no
    // cwd in it — which is how an inert conjunct passed as a working one.
    const { root_destructive_call: expected } = await loadPythonGate();
    const fromTs = ROOT_CALL_CORPUS.map(([command, cwd]) =>
      isRootDestructiveCall(command, { cwd }),
    );
    expect(fromTs).toEqual(expected);
  });

  test("both sides agree on what counts as management traffic", async () => {
    // The predicate whose per-branch ordering let a marker vouch for the rest of
    // its own line on one side and not the other.
    const { management: expected } = await loadPythonGate();
    const fromTs = MANAGEMENT_CORPUS.map(([tool, target, command]) =>
      isManagementCall(tool, { target, command }, HOME),
    );
    expect(fromTs).toEqual(expected);
  });
});
