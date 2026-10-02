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

import { createHash, createHmac, randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, realpathSync } from "node:fs";
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
import { reflexGate, toolCallTargets } from "./reflex.ts";
import { findPlugin, registerDispatchCommand, tokenizeArgs } from "./slash.ts";

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
  /\bgit\s+worktree\s+remove\b/,
  /\bgit\s+branch\s+-[dD]\b/,
  /\bherdr\s+pane\s+close\b/,
  /\bgh\s+release\s+create\b/,
  /\bterraform\s+(?:apply|destroy)\b/,
  /\bkubectl\s+delete\b/,
  /\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+\//,
  /\bgit\s+push\s+--force\b/,
]);

export const AUTHORIZATION_KEY_ENV = "HERDR_DISPATCH_RUNTIME_AUTH_KEY";

const PROTECTED_PYTHON_BOOTSTRAP = String.raw`
import importlib.abc, importlib.util, json, sys
bundle = json.load(sys.stdin)
class FrozenFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in bundle["modules"]:
            return importlib.util.spec_from_loader(fullname, self)
        return None
    def exec_module(self, module):
        source = bundle["modules"][module.__name__]
        module.__file__ = "/__protected__/lib/" + module.__name__ + ".py"
        exec(compile(source, module.__file__, "exec"), module.__dict__)
sys.meta_path.insert(0, FrozenFinder())
namespace = {"__name__": "__main__", "__file__": "/__protected__/bin/dispatch_plugin.py", "__package__": None}
exec(compile(bundle["plugin"], namespace["__file__"], "exec"), namespace)
`;

export function freezeProtectedLifecycleBundle(plugin) {
  if (!plugin) throw new Error("dispatch plugin not found");
  const root = path.dirname(path.dirname(plugin));
  const libDir = path.join(root, "lib");
  const modules = {};
  for (const entry of readdirSync(libDir)) {
    if (!entry.endsWith(".py") || entry === "__init__.py") continue;
    modules[entry.slice(0, -3)] = readFileSync(path.join(libDir, entry), "utf8");
  }
  return JSON.stringify({ plugin: readFileSync(plugin, "utf8"), modules });
}

function authorizationPayload(record) {
  return [
    record?.authorization_id,
    record?.action,
    record?.repo,
    record?.remote,
    record?.push_url,
    record?.ref,
    record?.destination_ref,
    record?.pr_url,
    record?.pr_base,
    record?.pr_head_ref,
    record?.cleanup_evidence_digest,
    record?.run_id,
    record?.lane,
    record?.dispatch_id,
    record?.gate_c_report_id,
    record?.revision,
    record?.outcome,
    record?.delivery_scope,
    record?.authorized_unix_ms,
    record?.consumed_unix_ms,
  ].map((value) => String(value ?? "")).join("\n");
}

export function authorizationProof(record, key) {
  if (!key) return "";
  return createHmac("sha256", key).update(authorizationPayload(record)).digest("hex");
}

function isAuthorizationProofValid(record, key) {
  return Boolean(
    record?.authorization_proof &&
    authorizationProof(record, key) === record.authorization_proof
  );
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function requiredCleanupSteps(binding, outcome) {
  if (outcome === "no_change") return [];
  const scope = String(binding?.delivery_scope ?? "");
  if (scope === "local") return ["docs_aligned"];
  if (scope === "repository") return ["docs_aligned", "child_pushed", "pr_merged"];
  if (scope === "submodule") {
    return ["docs_aligned", "child_pushed", "parent_pointer_updated", "pr_merged"];
  }
  return null;
}

function cleanupEvidenceDigestForGate(raw, gateC) {
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("evidence must be an object");
  }
  const steps = requiredCleanupSteps(gateC?.binding, gateC?.outcome ?? "delivered");
  if (!steps) throw new Error("unsupported Gate C delivery scope");
  const projection = {};
  for (const step of steps) projection[step] = parsed[step] ?? {};
  return createHash("sha256").update(stableJson(projection)).digest("hex");
}

function gateCProofPayload(gateC) {
  const binding = gateC?.binding ?? {};
  return [
    gateC?.report_id,
    gateC?.accepted,
    gateC?.outcome,
    binding?.repo,
    binding?.run_id,
    binding?.lane,
    binding?.dispatch_id,
    binding?.handoff,
    binding?.revision,
    binding?.delivery_scope,
    binding?.evidence_digest,
    gateC?.verified_unix_ms,
  ].map((value) => String(value ?? "")).join("\n");
}

export function gateCProof(gateC, key) {
  if (!key) return "";
  return createHmac("sha256", key).update(gateCProofPayload(gateC)).digest("hex");
}

function isGateCProofValid(gateC, key) {
  return Boolean(gateC?.gate_c_proof && gateCProof(gateC, key) === gateC.gate_c_proof);
}

/** True when the orchestrator is deliberately parked on worker IPC. */
export function isParked(state) {
  return state?.orchestrator_phase === "yield_and_guard";
}

/** Hooks that steer models or gate tools apply only while a real dispatch run is active. */
export function hasActiveRun(state) {
  if (state?.run_id || state?.__persisted_dispatch_state === true) return true;
  const lanes = Object.values(state?.lanes ?? {});
  return lanes.some((lane) => lane?.status !== "released" || lane?.phase !== "closed");
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

function canonicalPath(value) {
  const resolved = path.resolve(String(value ?? "."));
  try {
    return realpathSync(resolved);
  } catch {
    return resolved;
  }
}

function classifyAuthorizableCommand(command) {
  const tokens = tokenizeArgs(command);
  if (!tokens || tokens.length < 2) return null;

  if (tokens[0] === "git" && tokens[1] === "push") {
    const tail = tokens.slice(2);
    const safeFlags = new Set(["--set-upstream", "-u"]);
    if (tail.some((token) => token.startsWith("-") && !safeFlags.has(token))) {
      return null;
    }
    const positional = tail.filter((token) => token && !token.startsWith("-"));
    if (positional.length !== 2) return null;
    const [remote, refspec] = positional;
    const split = refspec.split(":");
    if (split.length !== 2 || !split[0] || !split[1]) return null;
    const destination = split[1].replace(/^refs\/heads\//, "");
    if (!destination || destination.startsWith("refs/")) return null;
    return {
      action: "git_push",
      remote,
      ref: destination,
      destination_ref: destination,
      revision: split[0],
    };
  }

  if (
    tokens.length === 6 &&
    tokens[0] === "gh" &&
    tokens[1] === "pr" &&
    tokens[2] === "merge" &&
    tokens[3] &&
    !tokens[3].startsWith("-") &&
    tokens[4] === "--match-head-commit" &&
    tokens[5] &&
    !tokens[5].startsWith("-")
  ) {
    return { action: "merge_pr", ref: tokens[3], revision: tokens[5] };
  }

  if (
    tokens.length === 4 &&
    tokens[0] === "herdr" &&
    tokens[1] === "pane" &&
    tokens[2] === "close" &&
    tokens[3]
  ) {
    return { action: "close_pane", ref: tokens[3] };
  }
  return null;
}

function hasCommandShape(tokens, executable, sequence) {
  for (let start = 0; start < tokens.length; start += 1) {
    if (tokens[start] !== executable) continue;
    let cursor = start + 1;
    for (const expected of sequence) {
      while (cursor < tokens.length && tokens[cursor] !== expected) cursor += 1;
      if (cursor >= tokens.length) return false;
      cursor += 1;
    }
    return true;
  }
  return false;
}

function structurallyDestructive(command) {
  const tokens = tokenizeArgs(command) ?? [];
  if (hasCommandShape(tokens, "git", ["push"])) return "git push";
  if (hasCommandShape(tokens, "gh", ["pr", "merge"])) return "gh pr merge";
  if (hasCommandShape(tokens, "git", ["worktree", "remove"])) return "git worktree remove";
  if (hasCommandShape(tokens, "git", ["branch", "-d"]) || hasCommandShape(tokens, "git", ["branch", "-D"])) {
    return "git branch delete";
  }
  if (hasCommandShape(tokens, "herdr", ["pane", "close"])) return "herdr pane close";
  return "";
}

function invokesPythonInterpreter(command) {
  const text = String(command ?? "");
  // Fail closed on shell indirection that binds a variable to a Python
  // interpreter, e.g. `p=python3; "$p" -c ...`. Token-only matching cannot
  // see the expanded executable, so detecting the binding itself is required.
  if (
    /(?:^|[;&|\s])(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*["']?(?:[^\s;|&"']*\/)?(?:python(?:\d+(?:\.\d+)*)?|pypy(?:\d+)?)["']?(?=$|[\s;|&])/m.test(text)
  ) {
    return true;
  }
  const tokens = tokenizeArgs(text) ?? [];
  return tokens.some((token) => {
    const value = String(token ?? "").trim();
    const first = value.split(/\s+/, 1)[0];
    // POSIX shells remove a backslash before a non-newline character when it
    // is used to escape part of a word. Normalize that form before matching so
    // `p\\ython3` cannot hide the interpreter name from the gate.
    const shellNormalized = first.replace(/\\([^\n])/g, "$1");
    const base = shellNormalized.split("/").pop() ?? "";
    return /^(?:python(?:\d+(?:\.\d+)*)?|pypy(?:\d+)?)$/.test(base);
  });
}

/** Classify a tool call for the human gate. */
export function classifyToolCall(toolName, input, cwd = "") {
  const shellLike = new Set(["bash", "python", "shell", "exec", "command"]);
  if (!shellLike.has(toolName)) {
    return { gated: false, reason: "" };
  }
  const command = toolCallTargets(input).command;
  if (
    toolName !== "python" &&
    /(?:\$|\x60|\\|[;&|]{1,2}|[<>])/.test(command)
  ) {
    return {
      gated: true,
      reason: "dynamic or compound shell execution is not an authorizable publication path",
      authority: null,
    };
  }
  if (toolName !== "python" && invokesPythonInterpreter(command)) {
    return {
      gated: true,
      reason: "shell-wrapped Python execution is not an authorizable publication path",
      authority: null,
    };
  }
  if (toolName === "python") {
    const processCapablePython =
      /\b(?:import\s+(?:subprocess|os|pty|importlib|ctypes)\b|from\s+(?:subprocess|os|pty|importlib|ctypes)\s+import\b|__import__\s*\(|importlib\.|subprocess\.|os\.(?:system|popen|spawn\w*|exec\w*)|pty\.spawn\s*\()/m;
    if (processCapablePython.test(command)) {
      return {
        gated: true,
        reason: "python process-capable code is not an authorizable publication path",
        authority: null,
      };
    }
  }
  const shape = structurallyDestructive(command);
  if (shape) {
    return {
      gated: true,
      reason: `destructive operation ${shape}`,
      authority: classifyAuthorizableCommand(command),
    };
  }
  for (const pattern of GATED_PATTERNS) {
    if (pattern.test(command)) {
      return {
        gated: true,
        reason: `destructive operation matching ${pattern}`,
        authority: classifyAuthorizableCommand(command),
      };
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
  let sessionRunActive = false;
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
  let runtimeAuthorizationKey = "";
  let protectedLifecycleBundle = "";
  const runtimeAuthorizationIds = new Set();
  const runtimeConsumedAuthorizationIds = new Set();
  const resolveGitRevision =
    options.gitRevision ??
    ((repo, ref) =>
      execFileSync("git", ["-C", repo, "rev-parse", ref], { encoding: "utf8" }).trim());
  const resolvePushUrl =
    options.pushUrl ??
    ((repo, remote) =>
      execFileSync("git", ["-C", repo, "remote", "get-url", "--push", remote], {
        encoding: "utf8",
      }).trim());
  const resolvePrHead =
    options.prHead ??
    ((repo, pr) =>
      execFileSync(
        "gh",
        ["pr", "view", String(pr), "--json", "headRefOid", "--jq", ".headRefOid"],
        { cwd: repo, encoding: "utf8" },
      ).trim());
  const resolvePrContext =
    options.prContext ??
    ((repo, pr) => {
      if (options.prHead) {
        return {
          headRefOid: resolvePrHead(repo, pr),
          headRefName: "",
          baseRefName: "main",
          url: `local-test://${canonicalPath(repo)}/pull/${String(pr)}`,
        };
      }
      return JSON.parse(
        execFileSync(
          "gh",
          ["pr", "view", String(pr), "--json", "headRefOid,headRefName,baseRefName,url"],
          { cwd: repo, encoding: "utf8" },
        ),
      );
    });

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

  function shouldAttachPersistedRun(state, persistedStateExists = false) {
    const lanes = Object.values(state?.lanes ?? {});
    // A persisted dispatch ledger with no surviving run/lane identity is
    // tampering/recovery evidence, not proof that no run exists. Ordinary OMP
    // sessions remain untouched because they have no persisted dispatch file.
    if (lanes.length === 0) return Boolean(state?.run_id || persistedStateExists);
    if (lanes.some((lane) => lane?.status !== "released" || lane?.phase !== "closed")) {
      return true;
    }
    for (const lane of lanes) {
      const paneId = lane?.pane_id ?? lane?.pane;
      if (!paneId) continue;
      const observed = lookupLifecyclePane(paneId);
      if (observed?.status !== "absent") return true;
    }
    return false;
  }

  const isRootCommandContext = (ctx) => !ctx?.agent || ctx.agent.kind !== "sub";

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

  function consumeHumanAuthorization(authority, cwd) {
    if (!statePath || !authority) return false;
    let matched = false;
    const repo = canonicalPath(cwd || ".");
    const result = updateState(statePath, (state) => {
      const records = state?.extra_data?.authorizations;
      if (!Array.isArray(records)) return state;
      for (const record of records) {
        if (
          record?.consumed_unix_ms ||
          !runtimeAuthorizationIds.has(record?.authorization_id) ||
          !isAuthorizationProofValid(record, runtimeAuthorizationKey) ||
          record?.action !== authority.action ||
          record?.ref !== authority.ref ||
          String(record?.remote ?? "") !== String(authority.remote ?? "") ||
          String(record?.destination_ref ?? "") !== String(authority.destination_ref ?? "") ||
          (record?.action === "git_push" && record?.revision !== authority.revision) ||
          record?.repo !== repo ||
          record?.run_id !== state?.run_id
        ) {
          continue;
        }
        const lane = state?.lanes?.[record.lane];
        const gateC = lane?.gate_c;
        if (
          !lane ||
          lane.run_id !== record.run_id ||
          lane.dispatch_id !== record.dispatch_id ||
          gateC?.accepted !== true ||
          !isGateCProofValid(gateC, runtimeAuthorizationKey) ||
          gateC?.report_id !== record.gate_c_report_id ||
          gateC?.binding?.revision !== record.revision ||
          String(gateC?.outcome ?? "delivered") !== String(record.outcome ?? "") ||
          String(gateC?.binding?.delivery_scope ?? "") !== String(record.delivery_scope ?? "")
        ) {
          continue;
        }

        if (record.action === "git_push") {
          let liveRevision = "";
          try {
            liveRevision = resolveGitRevision(repo, record.ref);
          } catch {
            continue;
          }
          if (liveRevision !== record.revision) continue;
          let livePushUrl = "";
          try {
            livePushUrl = resolvePushUrl(repo, record.remote);
          } catch {
            continue;
          }
          if (livePushUrl !== record.push_url) continue;
        }
        if (record.action === "merge_pr") {
          if (authority.revision !== record.revision) continue;
          let livePr = null;
          try {
            livePr = resolvePrContext(repo, record.ref);
          } catch {
            continue;
          }
          if (
            livePr?.headRefOid !== record.revision ||
            String(livePr?.url ?? "") !== String(record.pr_url ?? "") ||
            String(livePr?.baseRefName ?? "") !== String(record.pr_base ?? "") ||
            String(livePr?.headRefName ?? "") !== String(record.pr_head_ref ?? "")
          ) continue;
        }

        if (record.action === "remove_worktree") {
          const cleanup = lane?.cleanup_authorization;
          if (
            !cleanup ||
            cleanup.authorization_id !== record.authorization_id ||
            cleanup.run_id !== record.run_id ||
            cleanup.dispatch_id !== record.dispatch_id ||
            cleanup.worktree !== record.ref ||
            cleanup.gate_c_report_id !== record.gate_c_report_id ||
            cleanup.revision !== record.revision
          ) {
            continue;
          }
        }
        if (record.action === "close_pane") {
          if (
            lane?.pane_id !== record.ref ||
            lane?.status !== "released" ||
            lane?.phase !== "closed" ||
            !lane?.cleanup_finalized_unix_ms
          ) {
            continue;
          }
        }

        record.consumed_unix_ms = Date.now();
        record.authorization_proof = authorizationProof(record, runtimeAuthorizationKey);
        runtimeAuthorizationIds.delete(record.authorization_id);
        matched = true;
        break;
      }
      return state;
    });
    if (result?.ok && result.state) brain = result.state;
    return Boolean(result?.ok && matched);
  }

  function lifecycleLaneId(argv) {
    const index = argv.indexOf("--lane");
    return index >= 0 ? String(argv[index + 1] ?? "") : "";
  }

  function matchingRuntimeCleanupAuthority(state, laneId, repo, consumed) {
    const lane = state?.lanes?.[laneId];
    const gateC = lane?.gate_c;
    const binding = gateC?.binding;
    if (!lane || !gateC?.accepted || !binding) return null;
    const persistedCleanupWorktree = String(
      lane?.cleanup_authorization?.worktree ?? "",
    );
    const worktree = persistedCleanupWorktree ||
      (lane?.worktree ? canonicalPath(lane.worktree) : "");
    const records = state?.extra_data?.authorizations;
    if (!worktree || !Array.isArray(records)) return null;
    for (const record of records) {
      const id = record?.authorization_id;
      const isConsumed = Boolean(record?.consumed_unix_ms);
      if (
        record?.action !== "remove_worktree" ||
        record?.repo !== canonicalPath(repo) ||
        record?.ref !== worktree ||
        record?.run_id !== state?.run_id ||
        record?.lane !== laneId ||
        record?.dispatch_id !== lane?.dispatch_id ||
        record?.gate_c_report_id !== gateC?.report_id ||
        record?.revision !== binding?.revision ||
        String(record?.outcome ?? "delivered") !== String(gateC?.outcome ?? "delivered") ||
        String(record?.delivery_scope ?? "") !== String(binding?.delivery_scope ?? "") ||
        !isAuthorizationProofValid(record, runtimeAuthorizationKey) ||
        isConsumed !== consumed
      ) {
        continue;
      }
      if (consumed) {
        if (!runtimeConsumedAuthorizationIds.has(id)) continue;
      } else if (!runtimeAuthorizationIds.has(id) || runtimeConsumedAuthorizationIds.has(id)) {
        continue;
      }
      return record;
    }
    return null;
  }

  const runProtectedLifecycle =
    options.lifecycleRunner ??
    ((repo, subcommand, argv, key) => {
      if (!protectedLifecycleBundle) {
        throw new Error("protected lifecycle runtime was not frozen at session start");
      }
      const python = process.env.HERDR_DISPATCH_PYTHON ?? "python3";
      return execFileSync(
        python,
        ["-I", "-c", PROTECTED_PYTHON_BOOTSTRAP, "--repo", repo, subcommand, ...argv],
        {
          encoding: "utf8",
          input: protectedLifecycleBundle,
          env: { ...process.env, [AUTHORIZATION_KEY_ENV]: key },
        },
      );
    });

  if (typeof pi?.registerCommand === "function") {
    pi.registerCommand("authorize-action", {
      description:
        "Authorize one human-gated action for the current run: " +
        "<action> --lane <lane> [--remote <remote>] --ref <branch|pr|path|pane>",
      handler: async (args, ctx) => {
        if (!rootSession || !isRootCommandContext(ctx) || !sessionRunActive || !runtimeAuthorizationKey) {
          ctx?.ui?.notify?.(
            "authorize-action: only the active root OMP session may issue human authority",
            "error",
          );
          return;
        }
        const tokens = tokenizeArgs(args);
        const action = tokens?.[0] ?? "";
        const laneIndex = tokens?.indexOf("--lane") ?? -1;
        const refIndex = tokens?.indexOf("--ref") ?? -1;
        const remoteIndex = tokens?.indexOf("--remote") ?? -1;
        const evidenceIndex = tokens?.indexOf("--evidence") ?? -1;
        const laneId = laneIndex >= 0 ? tokens?.[laneIndex + 1] ?? "" : "";
        let ref = refIndex >= 0 ? tokens?.[refIndex + 1] ?? "" : "";
        const remote = remoteIndex >= 0 ? tokens?.[remoteIndex + 1] ?? "" : "";
        const cleanupEvidence = evidenceIndex >= 0 ? tokens?.[evidenceIndex + 1] ?? "" : "";
        const allowed = new Set([
          "git_push",
          "merge_pr",
          "remove_worktree",
          "close_pane",
        ]);
        if (!allowed.has(action) || !laneId || !ref) {
          ctx?.ui?.notify?.(
            "authorize-action: usage <git_push|merge_pr|remove_worktree|close_pane> " +
              "--lane <lane> [--remote <remote>] --ref <branch|pr|worktree|pane>",
            "error",
          );
          return;
        }

        const targetStatePath = resolveStatePath(ctx?.cwd ?? ".");
        const current = readState(targetStatePath);
        const lane = current?.lanes?.[laneId];
        const gateC = lane?.gate_c;
        if (
          current?.orchestrator_phase !== "human_gate" ||
          !current?.run_id ||
          !lane ||
          lane.run_id !== current.run_id ||
          !lane.dispatch_id ||
          gateC?.accepted !== true ||
          !isGateCProofValid(gateC, runtimeAuthorizationKey) ||
          !gateC?.report_id ||
          gateC?.binding?.run_id !== current.run_id ||
          gateC?.binding?.lane !== laneId ||
          gateC?.binding?.dispatch_id !== lane.dispatch_id ||
          !gateC?.binding?.revision
        ) {
          ctx?.ui?.notify?.(
            "authorize-action: current lane has no matching accepted Gate C binding",
            "error",
          );
          return;
        }

        const repo = canonicalPath(ctx?.cwd ?? ".");
        let cleanupEvidenceDigest = "";
        if (action === "remove_worktree") {
          ref = canonicalPath(path.resolve(repo, ref));
          const laneWorktree = lane?.worktree ? canonicalPath(lane.worktree) : "";
          if (!laneWorktree || ref !== laneWorktree) {
            ctx?.ui?.notify?.(
              "authorize-action: worktree ref does not match the current lane",
              "error",
            );
            return;
          }
          if (!cleanupEvidence) {
            ctx?.ui?.notify?.(
              "authorize-action: remove_worktree requires --evidence so cleanup prerequisites are human-attested",
              "error",
            );
            return;
          }
          try {
            cleanupEvidenceDigest = cleanupEvidenceDigestForGate(cleanupEvidence, gateC);
          } catch {
            ctx?.ui?.notify?.(
              "authorize-action: remove_worktree --evidence must match the current Gate C scope",
              "error",
            );
            return;
          }
        }
        let pushUrl = "";
        if (action === "git_push") {
          if (!remote) {
            ctx?.ui?.notify?.(
              "authorize-action: git_push requires --remote so destination scope is explicit",
              "error",
            );
            return;
          }
          if (lane?.branch && ref !== lane.branch) {
            ctx?.ui?.notify?.(
              "authorize-action: push ref does not match the current lane branch",
              "error",
            );
            return;
          }
          let liveRevision = "";
          try {
            liveRevision = resolveGitRevision(repo, ref);
          } catch {
            ctx?.ui?.notify?.(
              "authorize-action: cannot resolve the requested branch revision",
              "error",
            );
            return;
          }
          if (liveRevision !== gateC.binding.revision) {
            ctx?.ui?.notify?.(
              "authorize-action: branch revision changed after Gate C; re-run Gate C",
              "error",
            );
            return;
          }
          try {
            pushUrl = resolvePushUrl(repo, remote);
          } catch {
            ctx?.ui?.notify?.(
              "authorize-action: cannot resolve the push URL for the requested remote",
              "error",
            );
            return;
          }
          if (!pushUrl) {
            ctx?.ui?.notify?.(
              "authorize-action: resolved push URL is empty",
              "error",
            );
            return;
          }
        }
        let prContext = null;
        if (action === "merge_pr") {
          try {
            prContext = resolvePrContext(repo, ref);
          } catch {
            ctx?.ui?.notify?.(
              "authorize-action: cannot resolve the requested PR context",
              "error",
            );
            return;
          }
          if (prContext?.headRefOid !== gateC.binding.revision) {
            ctx?.ui?.notify?.(
              "authorize-action: PR head changed after Gate C; re-run Gate C",
              "error",
            );
            return;
          }
          if (!prContext?.url || !prContext?.baseRefName) {
            ctx?.ui?.notify?.(
              "authorize-action: PR repository/base context is incomplete",
              "error",
            );
            return;
          }
        }
        if (action === "close_pane" && (!lane?.pane_id || ref !== lane.pane_id)) {
          ctx?.ui?.notify?.(
            "authorize-action: pane ref does not match the current lane",
            "error",
          );
          return;
        }
        const destinationLines = [
          `action: ${action}`,
          `repo: ${repo}`,
          `ref: ${ref}`,
          `Gate C revision: ${gateC.binding.revision}`,
        ];
        if (action === "git_push") {
          destinationLines.push(
            `remote: ${remote}`,
            `push URL: ${pushUrl}`,
            `destination ref: ${ref}`,
          );
        }
        if (action === "merge_pr") {
          destinationLines.push(
            `PR: ${prContext?.url ?? ""}`,
            `base: ${prContext?.baseRefName ?? ""}`,
            `head: ${prContext?.headRefName ?? ""}`,
          );
        }
        if (action === "remove_worktree") {
          destinationLines.push(`cleanup evidence: ${cleanupEvidence}`);
        }
        const confirmed = await ctx?.ui?.confirm?.(
          "Authorize destructive action?",
          destinationLines.join("\n"),
        );
        if (confirmed !== true) {
          ctx?.ui?.notify?.("authorize-action: human confirmation declined or unavailable", "error");
          return;
        }

        const record = {
          authorization_id: `human-${randomUUID()}`,
          action,
          repo,
          remote: action === "git_push" ? remote : "",
          push_url: action === "git_push" ? pushUrl : "",
          ref,
          destination_ref: action === "git_push" ? ref : "",
          pr_url: action === "merge_pr" ? String(prContext?.url ?? "") : "",
          pr_base: action === "merge_pr" ? String(prContext?.baseRefName ?? "") : "",
          pr_head_ref: action === "merge_pr" ? String(prContext?.headRefName ?? "") : "",
          cleanup_evidence_digest: action === "remove_worktree" ? cleanupEvidenceDigest : "",
          run_id: current.run_id,
          lane: laneId,
          dispatch_id: lane.dispatch_id,
          gate_c_report_id: gateC.report_id,
          revision: gateC.binding.revision,
          outcome: gateC.outcome ?? "delivered",
          delivery_scope: gateC.binding.delivery_scope ?? "",
          authorized_unix_ms: Date.now(),
          consumed_unix_ms: 0,
        };
        record.authorization_proof = authorizationProof(record, runtimeAuthorizationKey);
        const written = updateState(targetStatePath, (state) => {
          if (
            state?.run_id !== record.run_id ||
            state?.lanes?.[laneId]?.dispatch_id !== record.dispatch_id ||
            state?.lanes?.[laneId]?.gate_c?.report_id !== record.gate_c_report_id
          ) {
            throw new Error("authorization binding became stale before commit");
          }
          state.extra_data ??= {};
          state.extra_data.authorizations ??= [];
          state.extra_data.authorizations.push(record);
          return state;
        });
        if (!written?.ok) {
          ctx?.ui?.notify?.(
            `authorize-action: ${written?.reason ?? "state update failed"}`,
            "error",
          );
          return;
        }
        runtimeAuthorizationIds.add(record.authorization_id);
        if (statePath === targetStatePath) brain = written.state;
        ctx?.ui?.notify?.(
          `authorize-action: recorded one-shot ${action} for ${ref}`,
          "info",
        );
      },
    });

    pi.registerCommand("verify-handoff", {
      description:
        "Run authenticated Gate C binding in the active root OMP session; direct worker binding is refused.",
      handler: async (args, ctx) => {
        if (
          !rootSession ||
          !isRootCommandContext(ctx) ||
          !sessionRunActive ||
          !runtimeAuthorizationKey ||
          !hasActiveRun(brain)
        ) {
          ctx?.ui?.notify?.(
            "verify-handoff: only the active root OMP dispatch session may bind Gate C",
            "error",
          );
          return;
        }
        const argv = tokenizeArgs(args);
        if (!argv) {
          ctx?.ui?.notify?.("verify-handoff: malformed arguments", "error");
          return;
        }
        const repo = canonicalPath(ctx?.cwd ?? ".");
        try {
          const output = runProtectedLifecycle(
            repo,
            "verify-handoff",
            argv,
            runtimeAuthorizationKey,
          );
          if (String(output ?? "").trim()) {
            ctx?.ui?.notify?.(String(output).trim(), "info");
          }
          const synced = readState(resolveStatePath(repo));
          if (synced) brain = synced;
        } catch (error) {
          const stderr = String(error?.stderr ?? "").trim();
          const message = stderr || String(error?.message ?? error);
          ctx?.ui?.notify?.(`verify-handoff: ${message}`, "error");
        }
      },
    });

    for (const subcommand of [
      "authorize-cleanup",
      "cleanup-worktree",
      "finalize-closeout",
    ]) {
      pi.registerCommand(subcommand, {
        description:
          "Run the protected #147 lifecycle executor in the active root OMP session.",
        handler: async (args, ctx) => {
          if (
            !rootSession ||
            !isRootCommandContext(ctx) ||
            !sessionRunActive ||
            !runtimeAuthorizationKey ||
            !hasActiveRun(brain)
          ) {
            ctx?.ui?.notify?.(
              `${subcommand}: only the active root OMP dispatch session may execute this command`,
              "error",
            );
            return;
          }
          const argv = tokenizeArgs(args);
          if (!argv) {
            ctx?.ui?.notify?.(`${subcommand}: malformed arguments`, "error");
            return;
          }
          const repo = canonicalPath(ctx?.cwd ?? ".");
          const laneId = lifecycleLaneId(argv);
          if (!options.lifecycleRunner) {
            const current = readState(resolveStatePath(repo));
            const consumed = subcommand === "finalize-closeout";
            const authority = matchingRuntimeCleanupAuthority(
              current,
              laneId,
              repo,
              consumed,
            );
            const cleanupId = current?.lanes?.[laneId]?.cleanup_authorization?.authorization_id;
            if (!authority || (consumed && authority.authorization_id !== cleanupId)) {
              ctx?.ui?.notify?.(
                `${subcommand}: no matching current-session ${consumed ? "consumed " : ""}` +
                  "human remove_worktree authority is active",
                "error",
              );
              return;
            }
          }
          try {
            const output = runProtectedLifecycle(
              repo,
              subcommand,
              argv,
              runtimeAuthorizationKey,
            );
            if (String(output ?? "").trim()) {
              ctx?.ui?.notify?.(String(output).trim(), "info");
            }
            const synced = readState(resolveStatePath(repo));
            if (synced) {
              brain = synced;
              if (!options.lifecycleRunner && subcommand === "cleanup-worktree") {
                const consumedId = synced?.lanes?.[laneId]?.cleanup_authorization?.authorization_id;
                const record = (synced?.extra_data?.authorizations ?? []).find(
                  (entry) => entry?.authorization_id === consumedId,
                );
                if (consumedId && record?.consumed_unix_ms) {
                  runtimeAuthorizationIds.delete(consumedId);
                  runtimeConsumedAuthorizationIds.add(consumedId);
                }
              }
            }
          } catch (error) {
            const stderr = String(error?.stderr ?? "").trim();
            const message = stderr || String(error?.message ?? error);
            ctx?.ui?.notify?.(`${subcommand}: ${message}`, "error");
          }
        },
      });
    }
  }

  // Registered before any event fires, so `/dispatch` is available from the
  // first prompt rather than appearing once a session has warmed up. The
  // command holds no gates of its own — it is a way to reach the bus, and the
  // bus is where lint, claim and atomicity live.
  registerDispatchCommand(pi, {
    onSuccess: () => {
      if (!statePath) return;
      const synced = readState(statePath);
      if (synced) {
        brain = synced;
        sessionRunActive = true;
      }
    },
  });

  pi.on("session_start", async (_event, eventCtx) => {
    if (!isRoot(eventCtx)) return;
    rootSession = true;
    runtimeAuthorizationKey = options.authorizationKey ?? randomUUID();
    runtimeAuthorizationIds.clear();
    runtimeConsumedAuthorizationIds.clear();
    protectedLifecycleBundle = "";
    sessionCtx = eventCtx;
    statePath = resolveStatePath(eventCtx.cwd);
    const persistedStateExists = existsSync(statePath);
    if (!options.lifecycleRunner) {
      try {
        protectedLifecycleBundle = freezeProtectedLifecycleBundle(findPlugin(eventCtx.cwd));
      } catch {
        // Ordinary OMP sessions must stay untouched. The protected command
        // itself fails loudly if a dispatch run later needs this runtime.
      }
    }
    try {
      brain = readState(statePath) ?? {
        orchestrator_phase: "contract",
        brain: { awaiting_lanes: [] },
      };
    } catch (error) {
      brain = {
        orchestrator_phase: "yield_and_guard",
        blocked_reason: `shared dispatch state unreadable; recovery required: ${error}`,
        brain: { awaiting_lanes: [] },
        lanes: {},
      };
      sessionRunActive = true;
      note(brain.blocked_reason);
      return;
    }

    sessionRunActive = shouldAttachPersistedRun(brain, persistedStateExists);
    if (
      persistedStateExists &&
      sessionRunActive &&
      !brain?.run_id &&
      Object.keys(brain?.lanes ?? {}).length === 0
    ) {
      brain = { ...brain, __persisted_dispatch_state: true };
    }

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
    runtimeAuthorizationIds.clear();
    runtimeConsumedAuthorizationIds.clear();
    protectedLifecycleBundle = "";
    runtimeAuthorizationKey = "";
    sessionRunActive = false;
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
    if (!rootSession || !isRoot(eventCtx) || !sessionRunActive || !hasActiveRun(brain)) return undefined;
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
    if (isRoot(eventCtx) && rootSession && sessionRunActive && brain) {
      // Re-evaluate retained finalized lanes against the live Herdr pane set on
      // every subsequent root tool call. The close-pane call itself stays
      // gated while its target exists; once the pane is physically absent the
      // same OMP session returns to ordinary behavior without a restart.
      sessionRunActive = shouldAttachPersistedRun(
        brain,
        Boolean(brain?.__persisted_dispatch_state || (statePath && existsSync(statePath))),
      );
    }
    const humanGate = classifyToolCall(
      event?.toolName,
      event?.input,
      eventCtx?.cwd ?? "",
    );
    // Dispatched workers may perform ordinary implementation work, but they
    // never inherit the root session's publication/destruction authority. A
    // worker attempting a protected action is blocked before any root-only
    // authorization record can be considered.
    if (!isRoot(eventCtx)) {
      if (!sessionRunActive || !hasActiveRun(brain)) return undefined;
      // Python is a general process-launch surface: lexical inspection cannot
      // soundly detect aliases, dynamic imports, ctypes, or constructed argv.
      // During an active dispatch, workers use the normal structured tool/shell
      // surfaces instead; Python execution stays root-only.
      if (event?.toolName === "python") {
        return {
          block: true,
          reason:
            "Python execution is root-only during an active dispatch because it can " +
            "bypass publication/destructive-action authorization.",
        };
      }
      const workerCommand = toolCallTargets(event?.input).command;
      if (
        ["bash", "shell", "exec", "command"].includes(String(event?.toolName ?? "")) &&
        /(?:ORCHESTRATOR_STATE\.json|(?:^|[\s"'=])(?:\.\.\/)*\.git\/dispatch(?:\/|\b)|(?:^|[\s"'=])\.dispatch\/)/.test(workerCommand)
      ) {
        return {
          block: true,
          reason:
            "The shared dispatch state is root-only during an active dispatch; " +
            "workers must not read, rewrite, move, or delete its persistence path.",
        };
      }
      if (!humanGate.gated) return undefined;
      return {
        block: true,
        reason:
          `${humanGate.reason}. Protected publication/destructive actions are root-only ` +
          "and require explicit human authority in the orchestrator session.",
      };
    }
    if (!rootSession || !sessionRunActive || !hasActiveRun(brain)) return undefined;

    const reflex = reflexGate(brain, event, {
      home: eventCtx?.home ?? process.env.HOME ?? "",
      cwd: eventCtx?.cwd ?? "",
    });
    let humanAuthorized = false;
    // Human authority may unlock only the human gate. A Gate A actor/location
    // refusal remains binding, and the authorization stays unconsumed.
    if (reflex.allowed && humanGate.gated && humanGate.authority) {
      humanAuthorized = consumeHumanAuthorization(
        humanGate.authority,
        eventCtx?.cwd ?? "",
      );
    }
    if (reflex.allowed && (!humanGate.gated || humanAuthorized)) return undefined;

    const reasons = [];
    if (humanGate.gated && !humanAuthorized) {
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

    let persisted;
    try {
      persisted = readState(statePath);
    } catch (error) {
      return {
        ok: false,
        reason: `shared dispatch state unreadable; recovery required: ${error}`,
      };
    }
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

    let persisted;
    try {
      persisted = readState(statePath);
    } catch (error) {
      return {
        ok: false,
        reason: `shared dispatch state unreadable; recovery required: ${error}`,
      };
    }
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
      sessionRunActive = hasActiveRun(next);
    },
    router,
    timers,
    isAttached: () => rootSession,
  };
}