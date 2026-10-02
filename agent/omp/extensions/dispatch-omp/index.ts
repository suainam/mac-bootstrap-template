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
 * So the guard is implemented only where it is actually available: the brain
 * state lives in the shared state file, and a parked reminder produces a
 * UI-only NOT VERIFIED diagnostic. It never calls `sendUserMessage`, because
 * an aside schedules a model continuation and defeats the park. A real blocked
 * todo still requires a host-side bridge or an extension todo API.
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

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import {
  checkPartition,
  isStalled,
  lookupHerdrAgent,
  readState,
  reconcileLanes,
  resolveStatePath,
  updateState,
  validateResumeArgv,
} from "./ledger.ts";

export { lookupHerdrAgent, resolveStatePath } from "./ledger.ts";
export {
  planPrune,
  planRollover,
  planDowngrade,
  classifyPressure,
  admitAgent,
  memoryFreeFraction,
  readHostMemory,
} from "./governance.ts";
export { parseNotify, laneFromSignature, paneFromSignature } from "./notify.ts";
export {
  BUSINESS_CODE_TOOLS,
  GateAVerdict,
  ISOLATED_ROOTS,
  PROBE_TOOLS,
  ROOT_DESTRUCTIVE_PATTERNS,
  THRESHOLD_ILLEGAL_PROBE,
  THRESHOLD_ROLE_BOUNDARY,
  TOOL_WHITELIST,
  WHITELIST_PATH_MARKERS,
  isBusinessCodePath,
  isIsolatedWorktree,
  isManagementCall,
  isProbeCommand,
  isRootDestructive,
  isRootDestructiveCall,
  isWhitelistedPath,
  reflexGate,
  reflexSteer,
} from "./reflex.ts";
export {
  parseHeartbeat,
  displayStage,
  heartbeatDue,
  heartbeatFields,
} from "./heartbeat.ts";
import {
  admitAgent,
  classifyPressure,
  memoryFreeFraction,
  planPrune,
  planRollover,
  readHostMemory,
} from "./governance.ts";
import {
  HEARTBEAT_MARKER,
  displayStage,
  heartbeatDue,
  heartbeatFields,
  parseHeartbeat,
} from "./heartbeat.ts";
import {
  NOTIFY_MARKER,
  laneFromSignature,
  paneFromSignature,
  parseNotify,
} from "./notify.ts";
import { reflexGate } from "./reflex.ts";
import { registerDispatchCommand } from "./slash.ts";

export {
  DISPATCH_DESCRIPTION,
  EXIT_CONTRACT,
  EXIT_DELIVERY_FAILED,
  EXIT_REFUSED,
  describeRefusal,
  findPlugin,
  parseDispatchArgs,
  registerDispatchCommand,
  runDispatch,
  tokenizeArgs,
} from "./slash.ts";

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

/**
 * Stall watchdog tuning: 10 minutes.
 *
 * Measured in polls against Herdr's monotonic `state_change_seq`, so the
 * threshold tracks actual reported progress rather than wall clock or how busy
 * a terminal looks. A lane whose sequence has not moved has genuinely reported
 * nothing new.
 */
export const DEFAULT_STALL_INTERVAL_MS = 60_000;
export const DEFAULT_STALL_POLLS = 3;
export const STALL_THRESHOLD_MS =
  DEFAULT_STALL_POLLS * DEFAULT_STALL_INTERVAL_MS;

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
 * @param {{lookupPane?: Function}} [options] injectable read-only lifecycle lookup for tests
 */
export default function dispatchBrain(pi, options = {}) {
  const lifecycleLookup = options.lookupPane ?? lookupHerdrAgent;
  const timers = new Set();
  const router = new RouterCursor();
  let brain = null;
  let rootSession = false;
  let stallPolls = 0;
  // Last observed Herdr state_change_seq per lane. Progress is measured by this
  // monotonic counter, never by the wall clock.
  const lastSeq = new Map();
  // Lanes whose [NOTIFY] arrived while parked, in arrival order.
  const inbox = [];
  // Heartbeats are evidence, not results: kept for the board, never acted on
  // as a completion.
  const heartbeats = [];
  const lastBeat = new Map();
  const stallByLane = new Map();
  // One-shot alarm latch: a stuck lane is reported once, not on every poll,
  // until it shows progress again.
  const alarmedLanes = new Set();
  // Query failures are visible once per lane but never converted to orphaned.
  const lifecycleUnknown = new Set();
  // Compacted stage per lane, republished as the sidebar `dstate` token.
  const sidebarStage = new Map();
  let statePath = null;
  let coldStart = { live: [], orphaned: [], unknown: [], resume: [] };
  let pressure = "ok";

  /** Recompute host pressure; a probe failure yields no opinion, not a freeze. */
  function hostPressureState() {
    pressure = classifyPressure(memoryFreeFraction(readHostMemory() ?? {}));
    return pressure;
  }

  /**
   * Context pressure for one lane.
   *
   * Kept separate from the stall watchdog: a stalled lane is quiet, while a
   * bloated lane is loud and expensive. Both are memory symptoms but only one
   * is a hang.
   */
  function contextPressure(tokens, options) {
    return {
      prune: planPrune(tokens, options),
      rollover: planRollover(tokens, options),
    };
  }
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

  const publishDstate = (value) => {
    if (!value) return;
    try {
      sessionCtx?.ui?.setStatus?.("dstate", value);
    } catch {
      // Sidebar projection is best effort; the shared ledger is authoritative.
    }
  };

  pi.setLabel?.(LABEL);

  // Registered before any event fires, so `/dispatch` is available from the
  // first prompt rather than appearing once a session has warmed up. The
  // command holds no gates of its own — it is a way to reach the bus, and the
  // bus is where lint, claim and atomicity live.
  registerDispatchCommand(pi, {
    onSuccess: () => {
      if (!statePath) return;
      const synced = readState(statePath);
      if (synced) brain = synced;
    },
  });

  pi.on("session_start", async (_event, eventCtx) => {
    if (!isRoot(eventCtx)) return;
    rootSession = true;
    sessionCtx = eventCtx;
    statePath = resolveStatePath(eventCtx.cwd);
    brain = readState(statePath) ?? {
      orchestrator_phase: "contract",
      brain: { awaiting_lanes: [] },
    };

    const restoredStage = Object.entries(brain?.lanes ?? {})
      .filter(([, lane]) => lane?.current_stage)
      .sort(
        ([, a], [, b]) =>
          Number(b?.last_heartbeat ?? 0) - Number(a?.last_heartbeat ?? 0),
      )[0];
    if (restoredStage) {
      const [laneId, lane] = restoredStage;
      const token = displayStage(lane.current_stage);
      if (token) {
        sidebarStage.set(laneId, token);
        publishDstate(token);
      }
    }

    // Cold start: adopt whatever survived, and flag what did not.
    try {
      const reconciled = reconcileColdStart();
      coldStart = reconciled;
      if (reconciled.orphaned.length > 0) {
        note(
          `dispatch: ${reconciled.orphaned.length} lane(s) did not survive the ` +
            `restart (${reconciled.orphaned.map((o) => o.laneId).join(", ")})`,
        );
      }
      if (reconciled.unknown.length > 0) {
        note(
          `dispatch: lifecycle status unknown for ${reconciled.unknown.length} lane(s) ` +
            `(${reconciled.unknown.map((o) => o.laneId).join(", ")}); claims remain held`,
        );
      }
      for (const entry of reconciled.resume) {
        if (!entry.ok) {
          note(`dispatch: lane ${entry.laneId} resume command rejected — ${entry.reason}`);
        }
      }
    } catch (error) {
      note(`dispatch: cold-start reconciliation skipped (${error})`);
    }

    // Startup diagnostics are UI-only. Injecting an aside here creates a
    // model turn during cold start, which is not evidence that any lane changed.
    try {
      if (
        (coldStart?.live?.length ?? 0) > 0 ||
        (coldStart?.orphaned?.length ?? 0) > 0 ||
        (coldStart?.unknown?.length ?? 0) > 0
      ) {
        const active = [
          ...(coldStart?.live ?? []),
          ...(coldStart?.orphaned ?? []),
          ...(coldStart?.unknown ?? []),
        ]
          .map((entry) => entry.laneId)
          .join(", ");
        eventCtx?.ui?.notify?.(
          `dispatch: recovered persisted run state for lane(s) ${active}`,
          "info",
        );
      }
    } catch {
      // UI diagnostics are best effort and must not abort session setup.
    }

    // The stall watchdog is a managed timer. A raw interval whose callback
    // throws would be fatal to the entire session.
    const handle = eventCtx.setInterval(() => {
      try {
        onStallPoll();
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
   * OMP 18.4.10 exposes no todo mutation API to extensions. A parked reminder
   * therefore cannot be turned into a native blocked todo from here. The safe
   * fallback is deliberately UI-only: do not inject an aside, because that
   * schedules the very continuation the guard is meant to suppress.
   */
  pi.on("todo_reminder", async (_event, eventCtx) => {
    if (!rootSession || !isRoot(eventCtx)) return;
    if (!brain || !isParked(brain)) return;
    note(
      `${parkGuardMessage(brain)} Native todo blocked mutation is unavailable ` +
        "to this extension host; blocked status is NOT VERIFIED.",
    );
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
   * Gate A + the human gate, at the tool boundary.
   *
   * Two independent gates on one hook, both evaluated, both reported. Gate A
   * asks whether the orchestrator is the right actor; the human gate asks
   * whether the operation is reversible. A command can fail either alone —
   * `rm -rf /` in a root checkout is both — so a refusal names every gate that
   * fired rather than the first to notice. Publication still leads with the
   * human-gate reason when both agree, because that is the binding constraint:
   * no amount of correct location makes it reversible.
   *
   * Subagent sessions are exempt from both. A dispatched lane *is* the worker,
   * and gating its tool calls would be the takeover in reverse. The check asks
   * the session who it is rather than counting nesting depth, because restricted
   * children rebind the parent's factories.
   */
  pi.on("tool_call", async (event, eventCtx) => {
    if (!rootSession || !isRoot(eventCtx)) return undefined;

    const reflex = reflexGate(brain, event, {
      home: eventCtx?.home ?? process.env.HOME ?? "",
      cwd: eventCtx?.cwd ?? "",
    });
    const humanGate = classifyToolCall(event?.toolName, event?.input);
    if (reflex.allowed && !humanGate.gated) return undefined;

    const reasons = [];
    if (humanGate.gated) {
      reasons.push(
        `${humanGate.reason}. Publishing and destructive changes require explicit ` +
          "human authorisation (human_gate); ask rather than proceeding.",
      );
    }
    if (!reflex.allowed) {
      reasons.push(`Gate A refused ${event?.toolName}: ${reflex.reason}`);

      // The steer is what turns a refusal into a correction. Without it the
      // model simply picks a different tool and the reflex reappears.
      try {
        pi.sendUserMessage?.(reflex.steer, {
          deliverAs: "aside",
          attribution: "agent",
        });
      } catch {
        // A refused steer must not break the block it was explaining.
      }
    }

    return { block: true, reason: reasons.join(" ") };
  });

  /**
   * Poll each parked lane and alarm on the ones that stopped progressing.
   *
   * Reads lifecycle state only. It never writes one.
   */
  function onStallPoll() {
    const waiting = brain?.brain?.awaiting_lanes ?? [];
    if (!isParked(brain) || waiting.length === 0) {
      stallPolls = 0;
      return;
    }

    const lanes = readState(statePath)?.lanes ?? {};
    let moved = false;

    for (const laneId of waiting) {
      const paneId = lanes?.[laneId]?.pane_id ?? lanes?.[laneId]?.pane;
      const observed = paneId ? lookupLifecyclePane(paneId) : { status: "absent", reason: "no pane recorded" };

      // A heartbeat inside the window is liveness evidence: reset this lane and
      // leave every other lane's counter alone. Note the polarity — a *recent*
      // beat clears the counter; `heartbeatDue` reports the opposite (that a
      // beat is missing or stale), so the branches are inverted deliberately.
      const beatAt = lastBeat.get(laneId) ?? lanes?.[laneId]?.last_heartbeat;
      const hasFreshBeat =
        Number.isFinite(beatAt) && !heartbeatDue(beatAt, Date.now(), STALL_THRESHOLD_MS);
      if (hasFreshBeat) {
        lastSeq.delete(laneId);
        stallByLane.delete(laneId);
        alarmedLanes.delete(laneId);
        continue;
      }

      if (observed?.status === "unknown") {
        if (!lifecycleUnknown.has(laneId)) {
          lifecycleUnknown.add(laneId);
          note(
            `dispatch watchdog: lifecycle status unknown for lane ${laneId}; ` +
              `claim remains held (${observed.reason ?? "lookup unavailable"})`,
          );
        }
        continue;
      }
      if (observed?.status === "absent") {
        if (!lifecycleUnknown.has(laneId)) {
          lifecycleUnknown.add(laneId);
          note(
            `dispatch watchdog: pane ${paneId || "-"} for lane ${laneId} is absent; recovery required`,
          );
        }
        continue;
      }
      lifecycleUnknown.delete(laneId);
      const info = observed?.status === "known" ? observed.info : observed;
      if (!info) continue;

      // Gate D: Semantic Watchdog lease extension (Issue #134). If an active lease
      // was granted (verified heavy compilation / test), do not alarm the human.
      const leaseUntil = lanes?.[laneId]?.watchdog_lease_until_unix_ms;
      if (Number.isFinite(leaseUntil) && leaseUntil > Date.now()) {
        stallByLane.set(laneId, 0);
        alarmedLanes.delete(laneId);
        continue;
      }

      const current = Number.isFinite(info.state_change_seq) ? info.state_change_seq : null;
      const previous = lastSeq.get(laneId) ?? null;
      lastSeq.set(laneId, current);

      // Progress clears both the counter and the one-shot alarm latch, so a
      // recovered lane can alarm again if it stalls a second time.
      if (previous !== null && current !== null && current > previous) {
        stallByLane.set(laneId, 0);
        alarmedLanes.delete(laneId);
      }

      const polls = (stallByLane.get(laneId) ?? 0) + 1;
      stallByLane.set(laneId, polls);
      if (!isStalled(previous, current, polls, DEFAULT_STALL_POLLS)) continue;
      if (alarmedLanes.has(laneId)) continue;
      alarmedLanes.add(laneId);
      moved = true;
      try {
        pi.sendUserMessage?.(
          `Dispatch watchdog: lane ${laneId} (pane ${paneId}) has reported no state ` +
            `change for ${Math.round(STALL_THRESHOLD_MS / 60000)} minutes. Inspect with ` +
            "`herdr agent get` and decide whether to nudge, abort or re-dispatch — " +
            "do not take over its work.",
          { deliverAs: "aside", attribution: "agent" },
        );
      } catch {
        // A refused steer must not kill the watchdog.
      }
    }

    stallPolls = moved ? 0 : stallPolls + 1;
  }

  /**
   * Drive the park open on a real worker report.
   *
   * This is the only routine path out of `yield_and_guard`. A todo reminder
   * deliberately does not appear here: it is not evidence a worker finished,
   * and treating it as such is the false-busywork loop the park exists to
   * prevent.
   */
  function consumeNotify(text) {
    const parsed = parseNotify(text);
    if (!parsed.ok) return parsed;

    const lane = laneFromSignature(parsed.notify.signature);
    const workerPane = paneFromSignature(parsed.notify.signature);
    parsed.notify.lane = lane;
    if (!lane) {
      return { ok: false, reason: "report has no registered lane identity" };
    }

    const persisted = readState(statePath);
    if (!persisted) {
      return { ok: false, reason: "shared dispatch state is unavailable" };
    }
    const laneState = persisted?.lanes?.[lane];
    if (!laneState || typeof laneState !== "object") {
      return { ok: false, reason: `report is for unregistered lane ${lane}` };
    }

    const expectedPane = String(laneState.pane_id ?? laneState.pane ?? "");
    const expectedRun = String(laneState.run_id ?? persisted.run_id ?? "");
    const expectedDispatch = String(laneState.dispatch_id ?? "");
    const expectedHandoff = String(laneState.handoff ?? "");

    if (!workerPane || workerPane !== expectedPane) {
      return { ok: false, reason: `report worker pane ${workerPane || "-"} does not match ${expectedPane || "-"}` };
    }
    if (!parsed.notify.runId || parsed.notify.runId !== expectedRun) {
      return { ok: false, reason: "report run identity is stale or missing" };
    }
    if (!parsed.notify.dispatchId || parsed.notify.dispatchId !== expectedDispatch) {
      return { ok: false, reason: "report dispatch identity is stale or missing" };
    }
    if (!parsed.notify.handoff || parsed.notify.handoff !== expectedHandoff) {
      return { ok: false, reason: "report handoff does not match the dispatched artifact" };
    }

    const waiting = new Set(persisted?.brain?.awaiting_lanes ?? []);
    if (!waiting.has(lane)) {
      if (laneState.phase === "done" && laneState.notified_at) {
        return { ok: true, notify: parsed.notify, duplicate: true, transitioned: false };
      }
      return { ok: false, reason: `report is for lane ${lane}, not one currently awaited` };
    }

    const lanePatch = {
      phase: "done",
      handoff: expectedHandoff,
      notified_at: Date.now(),
    };
    const partition = checkPartition(lanePatch, "extension");
    if (!partition.ok) return { ok: false, reason: partition.reason };

    const persistedResult = updateState(statePath, (state) => {
      const currentLane = state?.lanes?.[lane];
      if (!currentLane || typeof currentLane !== "object") {
        throw new Error(`lane ${lane} disappeared before notify commit`);
      }
      state.lanes[lane] = { ...currentLane, ...lanePatch };
      const currentWaiting = Array.from(state?.brain?.awaiting_lanes ?? []);
      state.brain = {
        ...(state.brain ?? {}),
        awaiting_lanes: currentWaiting.filter((id) => id !== lane),
        notifications_seen: Number(state?.brain?.notifications_seen ?? 0) + 1,
      };
      if (state.brain.awaiting_lanes.length === 0) {
        state.orchestrator_phase = "synthesis";
        state.blocked_reason = "";
      } else {
        state.orchestrator_phase = "yield_and_guard";
        state.blocked_reason = `Awaiting worker IPC [NOTIFY] on ${state.brain.awaiting_lanes.join(", ")}`;
      }
      return state;
    });
    if (!persistedResult.ok) return persistedResult;

    brain = persistedResult.state;
    inbox.push(parsed.notify);
    lastSeq.delete(lane);
    stallByLane.delete(lane);
    alarmedLanes.delete(lane);
    stallPolls = 0;

    const transitioned = brain.brain.awaiting_lanes.length === 0;
    if (transitioned) {
      try {
        pi.sendUserMessage?.(
          `Dispatch: ${lane} reported completion and all awaited lanes are terminal. ` +
            "Phase 0 advanced to synthesis — reconcile facts across lanes and state " +
            "the blockers you actually observed.",
          { deliverAs: "aside", attribution: "agent" },
        );
      } catch {
        // A refused wake steer must not undo the committed result.
      }
    } else {
      note(
        `dispatch: lane ${lane} completed; still awaiting ${brain.brain.awaiting_lanes.join(", ")}`,
      );
    }
    return { ok: true, notify: parsed.notify, transitioned };
  }

  /**
   * Absorb a stage heartbeat.
   *
   * Deliberately does *not* end the park. A heartbeat says "still working, and
   * here is where"; it is not a result. Ending the park on one would hand the
   * orchestrator back its own work mid-flight, which is precisely the
   * false-busywork loop the park exists to prevent.
   *
   * What it does do: refresh the lane's evidence, reset that lane's stall
   * counter, and publish the stage to the sidebar so a human can see the work is
   * live without asking.
   */
  function consumeHeartbeat(text, nowMs = Date.now()) {
    const parsed = parseHeartbeat(text);
    if (!parsed.ok) return parsed;

    const beat = parsed.beat;
    if (!beat.lane) {
      return { ok: false, reason: "heartbeat has no registered lane identity" };
    }
    const fields = heartbeatFields(beat, nowMs);
    const verdict = checkPartition(fields, "extension");
    if (!verdict.ok) return { ok: false, reason: verdict.reason };

    const persisted = readState(statePath);
    if (!persisted) {
      return { ok: false, reason: "shared dispatch state is unavailable" };
    }
    if (!persisted?.lanes?.[beat.lane]) {
      return { ok: false, reason: `heartbeat is for unregistered lane ${beat.lane}` };
    }
    const waiting = new Set(persisted?.brain?.awaiting_lanes ?? []);
    if (!waiting.has(beat.lane)) {
      return { ok: false, reason: `heartbeat is for lane ${beat.lane}, not one currently awaited` };
    }

    const persistedResult = updateState(statePath, (state) => {
      state.lanes[beat.lane] = {
        ...(state.lanes?.[beat.lane] ?? {}),
        ...fields,
      };
      return state;
    });
    if (!persistedResult.ok) return persistedResult;
    brain = persistedResult.state;

    heartbeats.push(beat);
    lastBeat.set(beat.lane, nowMs);

    // Liveness evidence resets the stall counter for this lane only. A second
    // lane going quiet must not be masked by the first lane reporting in.
    if (beat.lane) {
      lastSeq.delete(beat.lane);
      stallByLane.delete(beat.lane);
    }

    const stage = displayStage(beat.stage);
    if (stage) {
      sidebarStage.set(beat.lane, stage);
      publishDstate(stage);
    }

    return {
      ok: true,
      beat,
      fields,
      // The park is untouched; say so explicitly so a test can prove it.
      stillParked: isParked(brain),
      sidebarToken: stage ? { dstate: stage } : null,
    };
  }

  /** Look up a pane through the supported Herdr CLI without writing lifecycle state. */
  function lookupLifecyclePane(paneId) {
    try {
      return lifecycleLookup(paneId);
    } catch (error) {
      return { status: "unknown", reason: String(error) };
    }
  }

  /**
   * Cold-start reconciliation.
   *
   * Validates each lane's expected resume command and marks panes that did not
   * survive the restart as orphaned, keeping their evidence. Dispatch records
   * and validates the command; Herdr's `herdr:omp` integration is what attaches
   * it, because Herdr only accepts a resume command from an agent that already
   * holds the pane via lifecycle reporting — which this codebase must not do.
   */
  function reconcileColdStart() {
    const state = readState(statePath);
    if (!state) return { live: [], orphaned: [], unknown: [], resume: [] };

    const { live, orphaned, unknown } = reconcileLanes(state.lanes ?? {}, lookupLifecyclePane);

    const resume = [];
    for (const laneId of Object.keys(state.lanes ?? {})) {
      const lane = state.lanes[laneId] ?? {};
      if (!lane.expected_resume_argv) continue;
      const verdict = validateResumeArgv(lane.expected_resume_argv);
      resume.push({ laneId, ...verdict });
    }

    if (live.length > 0) {
      for (const entry of live) {
        if (Number.isFinite(entry.stateChangeSeq)) {
          lastSeq.set(entry.laneId, entry.stateChangeSeq);
        }
      }
    }
    return { live, orphaned, unknown, resume };
  }

  /**
   * Consume a worker report from a steer or user turn.
   *
   * Exposed on the handle so the same entry point serves both the automatic
   * path and a host that wants to feed a report in directly.
   */
  pi.on("input", async (event, eventCtx) => {
    if (!rootSession || !isRoot(eventCtx)) return undefined;
    const text = String(event?.text ?? "");

    // Heartbeat first: a text may carry both markers, and the heartbeat is the
    // weaker signal, so classifying it as a result would end the park.
    const beat = consumeHeartbeat(text);
    if (beat.ok) return { handled: true };
    if (text.includes(HEARTBEAT_MARKER)) {
      note(`dispatch: heartbeat refused: ${beat.reason ?? "invalid heartbeat"}`);
      return { handled: true };
    }

    const result = consumeNotify(text);
    if (result.ok) return { handled: true };
    if (text.includes(NOTIFY_MARKER)) {
      note(`dispatch: notify refused: ${result.reason ?? "invalid report"}`);
      return { handled: true };
    }
    return undefined;
  });

  // A small handle so tests can observe session state without reaching into
  // module internals. Harmless at runtime and keeps the hooks unit-testable.
  return {
    getState: () => brain,
    getColdStart: () => coldStart,
    contextPressure,
    getPressure: () => hostPressureState(),
    getInbox: () => inbox,
    getHeartbeats: () => heartbeats,
    /** Host memory pressure, recomputed on demand rather than cached. */
    hostPressure: () => classifyPressure(memoryFreeFraction(readHostMemory() ?? {})),
    admit: (weight = "heavy") => admitAgent(hostPressureState(), weight),
    getSidebarStages: () => Object.fromEntries(sidebarStage),
    consumeNotify,
    consumeHeartbeat,
    reconcileColdStart,
    tick: () => onStallPoll(),
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