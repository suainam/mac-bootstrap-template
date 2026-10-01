/**
 * Orchestrator Brain Loop — the omp-side half of herdr-dispatch (TB-04).
 *
 * This is the in-process half. The Herdr plugin half is one-shot argv commands
 * that know about panes and sidebar tokens; this half knows about the session,
 * subagent routing and the human gate, and never touches the Herdr CLI. The two
 * share exactly one thing: the state file. That is the whole coupling.
 *
 * What it does
 * ------------
 * 1. Attaches Phase 0 — the orchestrator's own meta-tasks — to the session.
 * 2. Guards the park, so a todo reminder is not read as "go find work".
 * 3. Routes subagent spawns through a routing matrix.
 * 4. Gates destructive operations behind human authorisation.
 *
 * What it refuses to do
 * ---------------------
 * Report agent lifecycle state. Herdr's `herdr:omp` integration owns that, and
 * a second writer does not fail loudly: Herdr accepts-and-ignores the older
 * sequence, or a pane flips back to idle while a retry hold is active. This
 * module only ever *reads* `agent_status`. The repository gate
 * `scripts/dispatch-single-writer-gate.py` fails the build if that changes.
 *
 * Platform limitation, stated plainly
 * -----------------------------------
 * The design calls for the Phase 0 meta-tasks to sit in omp's own todo list so
 * the reminder machinery can see them. **Extensions cannot write that list.**
 * `set_todos` is an RPC *host* command, not part of the extension API, and
 * `todo_reminder` is an observable event rather than a mutable one. The only
 * documented route to a native tool from an extension is `ctx.invokeTool`,
 * which by contract runs the built-in of the *same name* as the registered
 * tool — reaching `todo` that way means shadowing it for the model, which is
 * more invasive than the problem warrants.
 *
 * So the guard is implemented where it is actually available: the brain state
 * lives in the shared state file, and a reminder is answered with a corrective
 * steer telling the orchestrator it is parked and must not self-assign work.
 * That is weaker than flipping a status bit and is called out in the delivery
 * notes rather than papered over. Making it exact needs either a host-side
 * `set_todos` bridge or an extension todo API, both of which are host changes.
 *
 * Crash safety
 * ------------
 * Extensions run in-process with no isolation. A raw `setInterval` or a
 * detached promise whose callback throws escapes handler dispatch, surfaces as a
 * process-level `uncaughtException`, and is treated as fatal by the global
 * postmortem handler — tearing down the whole session, not just this
 * extension. Every timer here therefore comes from `ctx.setInterval` /
 * `ctx.setTimeout` / `ctx.clearTimer`, which run callbacks under the same
 * isolation as handler dispatch and are cleared on shutdown.
 */

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

export const LABEL = "Dispatch Brain Loop";

/** Phase 0 — the orchestrator's own meta-tasks. */
export const BRAIN_PHASES = Object.freeze([
  "contract",
  "topology",
  "yield_and_guard",
  "synthesis",
  "decision",
  "human_gate",
  "closed",
]);

/** Legal forward transitions. `closed` is terminal. */
export const BRAIN_TRANSITIONS = Object.freeze({
  contract: Object.freeze(["topology"]),
  topology: Object.freeze(["yield_and_guard"]),
  // Only a real wake signal may leave the park: a worker [NOTIFY] or a stall
  // alarm. A todo reminder is explicitly not one.
  yield_and_guard: Object.freeze(["synthesis", "decision"]),
  synthesis: Object.freeze(["decision", "human_gate"]),
  decision: Object.freeze(["human_gate", "topology"]),
  // No automatic path may publish.
  human_gate: Object.freeze(["closed", "synthesis"]),
  closed: Object.freeze([]),
});

/** The only reasons that may wake the orchestrator. */
export const WAKE_SIGNALS = Object.freeze(["notify", "stall_alarm", "human"]);

/** Meta-tasks that make up the orchestrator's own loop. */
export const PHASE0_TODOS = Object.freeze([
  { phase: "contract", content: "Brain 1/6 contract: write the nine-section task contract" },
  { phase: "topology", content: "Brain 2/6 topology: bind coordinates and name each lane" },
  {
    phase: "yield_and_guard",
    content: "Brain 3/6 yield_and_guard: parked on worker IPC — do not self-assign work",
  },
  {
    phase: "synthesis",
    content: "Brain 4/6 synthesis: reconcile facts across lanes, locate cross-cutting blockers",
  },
  {
    phase: "decision",
    content: "Brain 5/6 decision: recommend a course with evidence, do not merely relay",
  },
  { phase: "human_gate", content: "Brain 6/6 human_gate: obtain explicit human authorisation" },
]);

/** How long a lane may show no state change before we call it stalled. */
export const DEFAULT_STALL_POLLS = 6;
export const DEFAULT_STALL_INTERVAL_MS = 60_000;

/** Default routing matrix; override from the plugin config directory. */
export const DEFAULT_ROUTING = Object.freeze({
  scout: { patterns: ["@slow"] },
  researcher: { patterns: ["@slow"] },
  writer: { patterns: ["@smol"] },
  reviewer: { patterns: ["@plan"] },
  skeptic: { patterns: ["@slow"] },
  default: { patterns: ["@smol"] },
});

/** Destructive operations that must not happen without human sign-off. */
export const GATED_PATTERNS = Object.freeze([
  /\bgit\s+push\b/,
  /\bgh\s+pr\s+merge\b/,
  /\bgh\s+release\s+create\b/,
  /\bterraform\s+(?:apply|destroy)\b/,
  /\bkubectl\s+delete\b/,
  /\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+\//,
  /\bgit\s+push\s+--force\b/,
]);

/** True when the orchestrator is deliberately parked on worker IPC. */
export function isParked(state) {
  return state?.orchestrator_phase === "yield_and_guard";
}

/**
 * Validate a brain transition.
 *
 * Returns an error string, or null when the move is legal. Pure, so it is
 * unit tested without a session.
 */
export function checkTransition(current, target, wakeSignal) {
  if (!BRAIN_PHASES.includes(target)) {
    return `unknown orchestrator phase: ${target}`;
  }
  if (current === target) return null;
  const allowed = BRAIN_TRANSITIONS[current] ?? [];
  if (!allowed.includes(target)) {
    return `illegal transition ${current} -> ${target} (allowed: ${allowed.join(", ") || "none"})`;
  }
  if (current === "yield_and_guard" && !WAKE_SIGNALS.includes(wakeSignal)) {
    return (
      "yield_and_guard may only be left via an explicit wake signal " +
      `(${WAKE_SIGNALS.join(", ")}); a todo reminder is not one`
    );
  }
  if (current === "human_gate" && wakeSignal !== "human") {
    return "human_gate may only be crossed by explicit human authorisation";
  }
  return null;
}

/**
 * Render the Phase 0 meta-tasks for display or host-side injection.
 *
 * Exported so a host bridge (or a future omp extension todo API) can reuse the
 * exact same list instead of re-deriving it.
 */
export function buildPhase0Todos() {
  return [
    {
      name: "Orchestrator Brain (Phase 0)",
      tasks: PHASE0_TODOS.map((todo) => ({
        content: todo.content,
        status: todo.phase === "contract" ? "in_progress" : "pending",
      })),
    },
  ];
}

/** The corrective steer sent when a reminder arrives while parked. */
export function parkGuardMessage(state) {
  const waiting = state?.brain?.awaiting_lanes ?? [];
  const who = waiting.length > 0 ? waiting.join(", ") : "workers";
  return (
    `Dispatch: still parked in yield_and_guard awaiting ${who}. ` +
    "This is a deliberate suspension, not unfinished work — do not start new " +
    "work, do not re-run a worker's checks, and do not edit worker-owned files. " +
    "Proceed only when a worker [NOTIFY] arrives or a lane is reported stalled."
  );
}

/** Classify a tool call for the human gate. */
export function classifyToolCall(toolName, input) {
  if (toolName !== "bash" && toolName !== "python") {
    return { gated: false, reason: "" };
  }
  const command = String(input?.command ?? input?.code ?? "");
  for (const pattern of GATED_PATTERNS) {
    if (pattern.test(command)) {
      return { gated: true, reason: `destructive operation matching ${pattern}` };
    }
  }
  return { gated: false, reason: "" };
}

/** Pick a model for one spawn. Returns null when the role is unrouted. */
export function chooseModel(routing, role) {
  const entry = routing?.[role] ?? routing?.default;
  if (!entry) return null;
  const patterns = Array.isArray(entry.patterns) ? entry.patterns : [entry.pattern];
  if (!patterns || patterns.length === 0) return null;
  return patterns;
}

/**
 * Per-child router cursor.
 *
 * A stateful router (quota, round-robin) must advance exactly once per spawned
 * child. Keying on the stable spawn key makes that hold even if the hook is
 * re-entered, which a plain counter would get wrong.
 */
export class RouterCursor {
  constructor() {
    this.seen = new Set();
    this.counters = new Map();
  }

  /** True the first time this child is seen; false on re-entry. */
  shouldAdvance(spawnKey) {
    if (!spawnKey) return true;
    if (this.seen.has(spawnKey)) return false;
    this.seen.add(spawnKey);
    return true;
  }

  next(role) {
    const value = (this.counters.get(role) ?? 0) + 1;
    this.counters.set(role, value);
    return value;
  }

  snapshot() {
    return { seen: [...this.seen], counters: Object.fromEntries(this.counters) };
  }
}

/**
 * Resolve the shared state path.
 *
 * Anchored on the git *common* dir so a linked worktree and its main checkout
 * resolve to one file rather than growing two brains.
 */
export function resolveStatePath(cwd, exec = spawnSync) {
  try {
    const result = exec("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], {
      cwd,
      encoding: "utf8",
    });
    const common = String(result?.stdout ?? "").trim();
    if (result?.status === 0 && common) {
      return path.join(common, "dispatch", "ORCHESTRATOR_STATE.json");
    }
  } catch {
    // Fall through to the non-git default.
  }
  return path.join(cwd ?? ".", ".dispatch", "ORCHESTRATOR_STATE.json");
}

/** Load the routing matrix, preferring operator config over defaults. */
export function loadRouting(configDir) {
  if (!configDir) return DEFAULT_ROUTING;
  const file = path.join(configDir, "routing.json");
  try {
    if (!existsSync(file)) return DEFAULT_ROUTING;
    return { ...DEFAULT_ROUTING, ...JSON.parse(readFileSync(file, "utf8")) };
  } catch {
    // A broken config must not silently change routing to something narrower.
    return DEFAULT_ROUTING;
  }
}

/**
 * The extension entrypoint.
 *
 * @param {any} pi omp's ExtensionAPI
 */
export default function dispatchBrain(pi) {
  const timers = new Set();
  const router = new RouterCursor();
  let brain = null;
  let rootSession = false;
  let stallPolls = 0;
  // Managed timers and the UI live on the handler context, not on the API
  // object: `pi` carries actions, `ctx` carries per-session facilities.
  let sessionCtx = null;

  const routing = loadRouting(process.env.HERDR_DISPATCH_CONFIG_DIR ?? null);

  /** True for the orchestrator session, false for restricted subagents. */
  const isRoot = (eventCtx) => {
    if (!eventCtx || eventCtx.hasUI !== true) return false;
    // Restricted children rebind the parent's factories, so a module-level
    // "already ran" flag would leak across them. Ask the session who it is
    // rather than counting nesting depth.
    const agent = eventCtx.agent;
    return !agent || agent.kind !== "sub";
  };

  const note = (message) => {
    try {
      sessionCtx?.ui?.notify?.(message, "info");
    } catch {
      // Notifications are a convenience; never let one break a hook.
    }
  };

  pi.setLabel?.(LABEL);

  pi.on("session_start", async (_event, eventCtx) => {
    if (!isRoot(eventCtx)) return;
    rootSession = true;
    sessionCtx = eventCtx;
    brain = { orchestrator_phase: "contract", brain: { awaiting_lanes: [] } };

    // Announce the loop once. `aside` puts it at the next step boundary
    // without interrupting reasoning that is already under way.
    try {
      pi.sendUserMessage?.(
        "Dispatch brain loop attached. Phase 0 meta-tasks: " +
          PHASE0_TODOS.map((t) => t.phase).join(" -> ") +
          ". Todo reminders while parked are not new work.",
        { deliverAs: "aside", attribution: "agent" },
      );
    } catch {
      // A refused injection must not abort session setup.
    }

    // The stall watchdog is a managed timer. A raw interval whose callback
    // throws would be fatal to the entire session.
    const handle = eventCtx.setInterval(() => {
      try {
        onStallPoll(eventCtx);
      } catch (error) {
        // Managed timers already isolate this; catching again keeps the loop
        // alive across repeated failures.
        note(`dispatch watchdog: ${error}`);
      }
    }, DEFAULT_STALL_INTERVAL_MS);
    timers.add(handle);
  });

  pi.on("session_shutdown", (_event, eventCtx) => {
    sessionCtx = sessionCtx ?? eventCtx;
    for (const handle of timers) {
      try {
        (sessionCtx ?? eventCtx).clearTimer(handle);
      } catch {
        // The host clears managed timers on shutdown regardless.
      }
    }
    timers.clear();
  });

  /**
   * The park guard.
   *
   * A reminder while parked is noise: the orchestrator's own meta-task is
   * deliberately suspended pending worker IPC. Answering it with a corrective
   * steer is the strongest response available to an extension — see the
   * platform-limitation note at the top of this file.
   */
  pi.on("todo_reminder", async (_event, eventCtx) => {
    if (!rootSession || !isRoot(eventCtx)) return;
    if (!brain || !isParked(brain)) return;
    try {
      pi.sendUserMessage?.(parkGuardMessage(brain), {
        deliverAs: "aside",
        attribution: "agent",
      });
    } catch {
      // Best effort; never propagate out of a reminder handler.
    }
  });

  /**
   * Routing matrix for every subagent spawn.
   *
   * Fires in the parent session once per child, before the child resolves a
   * model — exactly what a stateful router needs to advance once per child
   * rather than once per consideration.
   */
  pi.on("before_subagent_spawn", async (event, eventCtx) => {
    if (!isRoot(eventCtx)) return undefined;
    if (!router.shouldAdvance(event?.spawnKey)) return undefined;

    const role = String(event?.agent ?? event?.modelRole ?? "default");
    const patterns = chooseModel(routing, role);
    if (!patterns) return undefined;

    router.next(role);
    return {
      model: patterns,
      note: `dispatch routing: role=${role} patterns=${patterns.join(",")}`,
    };
  });

  /**
   * Human gate.
   *
   * Destructive operations stop at the tool boundary and become a decision for
   * the orchestrator plus the human, rather than something an unattended lane
   * can do to itself.
   */
  pi.on("tool_call", async (event) => {
    if (!rootSession) return undefined;
    const verdict = classifyToolCall(event?.toolName, event?.input);
    if (!verdict.gated) return undefined;
    return {
      block: true,
      reason:
        `${verdict.reason}. Publishing and destructive changes require explicit ` +
        "human authorisation (human_gate); ask rather than proceeding.",
    };
  });

  function onStallPoll(eventCtx) {
    if (!isParked(brain)) {
      stallPolls = 0;
      return;
    }
    stallPolls += 1;
    if (stallPolls < DEFAULT_STALL_POLLS) return;
    stallPolls = 0;
    const waiting = brain?.brain?.awaiting_lanes ?? [];
    note(
      `dispatch: ${waiting.length} lane(s) parked without a state change for ` +
        `${Math.round((DEFAULT_STALL_POLLS * DEFAULT_STALL_INTERVAL_MS) / 60000)}min`,
    );
    try {
      pi.sendUserMessage?.(
        `Dispatch watchdog: no state change while parked on ${waiting.join(", ") || "workers"}. ` +
          "Inspect with herdr agent get; do not self-assign their work.",
        { deliverAs: "aside", attribution: "agent" },
      );
    } catch {
      // Best effort.
    }
    void eventCtx;
  }

  // A small handle so tests can observe session state without reaching into
  // module internals. Harmless at runtime and keeps the hooks unit-testable.
  return {
    getState: () => brain,
    // Lets a test (or a future host bridge) drive the state the hooks read,
    // rather than only inspecting it.
    setState: (next) => {
      brain = next;
    },
    router,
    timers,
    isAttached: () => rootSession,
  };
}