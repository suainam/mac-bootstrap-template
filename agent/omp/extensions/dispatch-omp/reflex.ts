/**
 * Gate A: the PreToolUse reflex gate (Issue #133).
 *
 * Why this is a separate module
 * -----------------------------
 * `index.ts` polices the orchestrator's *named steps* — the phase whitelist and
 * the human gate. A tool call is not a named step. The orchestrator can reach
 * straight into a worker's file with `read_file` and never appear in the phase
 * matrix at all, which is how "just checking" becomes child-work takeover.
 *
 * So the decision is made here, at the tool boundary, and kept pure so it can be
 * exercised without a session: `reflexGate` takes a tool call and a brain state
 * and returns a verdict. `index.ts` only supplies the state and enforces.
 *
 * Three layers, ordered by cost
 * -----------------------------
 * 1. **Whitelist bypass** — `todo`, the state file, the handoffs directory, the
 *    orchestrator's own task contract. Settled locally. The park produces a lot
 *    of legitimate management traffic and a model call per reminder would cost
 *    more than it decides, so this layer opens no socket at all.
 * 2. **Mechanical interception** — two facts, no judgment needed: a business-code
 *    read while parked, and a destructive workspace command aimed at a canonical
 *    root checkout. The second is an incident written down: `git reset --hard`
 *    in a root checkout loses whatever was uncommitted there, and nothing in a
 *    lane can undo it. It is refused in *every* phase, and permitted only inside
 *    an isolated lane worktree.
 * 3. **Jev semantics** — what remains is a question of role, not of fact. That
 *    question belongs to `orchestrator_guard.py`, which owns the TypeSafe client
 *    and the offline fallback. This module takes the answer as an injected
 *    `semantic` delegate rather than opening a socket of its own.
 *
 *    Stated plainly, because the earlier draft of this file implied more: **the
 *    in-process extension runs the mechanical layers only.** `index.ts` does not
 *    pass a delegate, so a model call would mean a subprocess on the tool-call
 *    hot path — the wrong trade for a judgement that only the ambiguous calls
 *    need. The semantic layer is reachable through `dispatch_plugin.py gate`,
 *    which is where a host that can afford it runs it. Nothing is lost: every
 *    refusal that matters is decided by layers 0–2, which never needed the model.
 *
 * Mirrors the Python gate on purpose
 * -----------------------------------
 * The two halves must agree or the seam becomes a hole: the Python side is the
 * authority, and this side is the fast path that runs in-process before it. Each
 * rule that appears here has a counterpart there, and a test asserts the
 * constants line up and the classifiers agree, so one cannot drift from the
 * other.
 *
 * Root checkout protection, stated as a rule
 * -----------------------------------------
 * Destructive commands belong in `.worktrees/` or `.herdr/worktrees/`, and only
 * there. Anywhere else — a canonical root, a submodule root, an ordinary source
 * tree — the working tree is the one copy of somebody's uncommitted work, and
 * there is no second copy to restore from.
 *
 * Two things this gate deliberately does *not* do, so nobody mistakes it for
 * more than it is:
 *
 * - **It does not parse a shell.** Commands are matched as text, so `sh -c` with
 *   an encoded payload, a script file, or an alias is outside what it can see.
 *   That is an accepted limitation, not an oversight — matching the text catches
 *   `&&` chaining, subshells and `xargs` as substrings, which is most of the
 *   realistic accidental cases.
 * - **It is not a sandbox.** It refuses what it recognises; it cannot stop a
 *   process that already started. The boundary it enforces is the orchestrator's
 *   own tool calls, which is where the incident happened.
 */

/** Tools that name a file. */
export const BUSINESS_CODE_TOOLS = Object.freeze([
  "read_file",
  "view_file",
  "write_file",
  "replace_file_content",
  "edit_file",
  "create_file",
  "apply_patch",
]);

/** Tools that run a command. */
export const PROBE_TOOLS = Object.freeze(["bash", "shell", "python", "exec", "command"]);

/** Pure management tools: no target, no tree, no judgment. */
export const TOOL_WHITELIST = Object.freeze([
  "todo",
  "todowrite",
  "todowrite_tool",
  "read_todos",
  "set_todos",
]);

/** Paths the orchestrator may read at any time. */
export const WHITELIST_PATH_MARKERS = Object.freeze([
  "ORCHESTRATOR_STATE.json",
  "CHECKPOINT.json",
  "/Documents/handoffs/",
  "/tmp/handoff/",
  ".dispatch_task_",
  "/.dispatch/",
]);

/** Worktree isolation roots — the only places a destructive command is safe. */
export const ISOLATED_ROOTS = Object.freeze([
  "/.worktrees/",
  "/.herdr/worktrees/",
  "/worktrees/",
]);

/** Thresholds from Issue #133. Both block strictly above 0.40. */
export const THRESHOLD_ROLE_BOUNDARY = 0.4;
export const THRESHOLD_ILLEGAL_PROBE = 0.4;

const SOURCE_SUFFIXES = Object.freeze([
  ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".rs", ".go", ".rb", ".java",
  ".kt", ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".sh", ".zsh", ".bash",
]);

/**
 * Commands that destroy uncommitted work or rewrite history.
 *
 * `git reset --hard` and `git clean -fd` are the two that lose a day. The rest
 * either lose one or publish one, so they belong in the same class — a gate that
 * draws the line at exactly the two commands from the incident report is a gate
 * that is one flag away from failing again.
 */
/**
 * Commands that destroy uncommitted work or rewrite history.
 *
 * Every git pattern tolerates global flags between `git` and the subcommand,
 * because `git -C <root> clean -fd` is the same destruction with a detour, and a
 * pattern demanding `git clean` adjacently does not see it at all.
 */
const GIT = /\bgit\b[^|;&|]*?\s+/;

export const ROOT_DESTRUCTIVE_PATTERNS = Object.freeze([
  new RegExp(`${GIT.source}reset\\b(?![^|;&]*--soft)(?![^|;&]*--mixed)(?![^|;&]*--merge)`),
  new RegExp(`${GIT.source}clean\\b[^|;&]*-[a-z]*f`),
  new RegExp(`${GIT.source}checkout\\s+(--\\s+)?\\.`),
  new RegExp(`${GIT.source}restore\\b[^|;&]*\\s+\\.`),
  // `git switch --discard-changes` is the modern spelling of `checkout .`.
  new RegExp(`${GIT.source}switch\\b[^|;&]*--discard-changes`),
  new RegExp(`${GIT.source}stash\\s+(drop|clear)`),
  new RegExp(`${GIT.source}push\\b[^|;&]*(--force|-f)\\b`),
  // Removing a worktree deletes a directory a peer agent may be running tests
  // in — orchestrator lesson 2, and the reason one-lane-one-worktree exists.
  new RegExp(`${GIT.source}worktree\\s+remove\\b`),
  new RegExp(`${GIT.source}branch\\s+-D\\b`),
  // `rm` with a recursive or force flag, in either spelling. A gate that knows
  // only `-rf` is one refactor from failing, and `--recursive --force` is what a
  // script written to avoid short flags produces.
  /\brm\b(?=[^|;&]*\s-{1,2}(?:[a-zA-Z]*r[a-zA-Z]*|recursive|force))/,
]);

/**
 * The directory a git command names with `-C`, `--git-dir` or `--work-tree`.
 *
 * Collected so the isolation check can judge the command's real target rather
 * than only the cwd it happens to run from — a lane worktree running
 * `git -C <root> clean -fd` is a root checkout reached through the back door.
 */
const GIT_DIR_FLAG_RE = /(?:^|(?<=[\s;&|]))(?:-C|--git-dir|--work-tree)(?:[=\s]+|\s*)(\S+)/g;

/** Commands that inspect a tree rather than driving the bus. */
export const PROBE_COMMAND_PATTERNS = Object.freeze([
  /\bgit\s+(status|diff|log|show|blame|ls-files|whatchanged)\b/,
  /\b(pytest|vitest|jest|mocha|cargo\s+(?:test|build|check)|go\s+test)\b/,
  /\b(npm|pnpm|yarn|bun)\s+(?:run\s+)?(test|build|check|lint)\b/,
  /\b(make\s+(check|test|ci)|ruff|mypy|eslint|tsc)\b/,
  /(?:^|(?<=[\s;&|(]))(cat|head|tail|less|grep|rg|ag|awk)\b/,
  /(?:^|(?<=[\s;&|(]))(ls|find|fd|stat|wc|du|file)\b/,
  /(?:^|(?<=[\s;&|(]))diff\b/,
]);

/** Source inside a lane worktree, named by a shell command. */
const LANE_CODE_RE =
  /(?:\.worktrees|\.herdr\/worktrees|worktrees)\/[^\s'";|&]*[^\s'";|&]*\.(?:py|ts|tsx|js|jsx|mjs|rs|go|rb|java|kt|swift|c|cc|cpp|h|hpp|sh|zsh|bash)\b/;

/** Any source filename token, wherever it appears. */
const SOURCE_TOKEN_RE =
  /[^\s'";|&]*\.(?:py|ts|tsx|js|jsx|mjs|rs|go|rb|java|kt|swift|c|cc|cpp|h|hpp|sh|zsh|bash)\b/;

const PLUGIN_ENTRY_RE = /dispatch_plugin\.py\s+([a-z_]+)/;
const WHITELISTED_PLUGIN_COMMANDS = Object.freeze([
  "status", "render_board", "harvest", "board", "gate", "guard", "startup",
]);

/** Verdict values, matching the Python `GateAVerdict` enum one for one. */
export const GateAVerdict = Object.freeze({
  WHITELISTED: "WHITELISTED",
  ALLOW: "ALLOW",
  REFUSE_CHILD_CODE: "REFUSE_CHILD_CODE",
  REFUSE_PROBE: "REFUSE_PROBE",
  REFUSE_ROOT_DESTRUCTIVE: "REFUSE_ROOT_DESTRUCTIVE",
  REFUSE_SEMANTIC: "REFUSE_SEMANTIC",
});

/** Expand `~` so a marker written as `~/Documents` still compares equal. */
function expandPath(text, home) {
  const raw = (text ?? "").trim();
  if (!raw) return "";
  if (raw === "~") return home;
  if (raw.startsWith("~/")) return `${home}/${raw.slice(2)}`;
  return raw;
}

/**
 * Whether a path names the run's own management surface.
 *
 * The path is *normalised* before the comparison. Without that,
 * `.dispatch/../src/app.py` contains the marker and the marker is exactly what
 * the whitelist looks for — so the whitelist would vouch for a read of a lane's
 * source, the one thing it exists to prevent. A whitelist that can be walked out
 * of with `..` is not one.
 */
export function isWhitelistedPath(target, home = "") {
  const path = expandPath(target, home);
  if (!path) return false;
  return WHITELIST_PATH_MARKERS.some((marker) => normalisePath(path).includes(marker));
}

export function isBusinessCodePath(target, home = "") {
  // The whitelist check runs on the *original* case, before lowercasing. Doing
  // it afterwards compares the markers — which are cased like
  // `ORCHESTRATOR_STATE.json` — against a lowercased path, so they could never
  // match and every handoff or task contract carrying a source suffix would read
  // as business code.
  const path = expandPath(target, home);
  if (!path) return false;
  if (isWhitelistedPath(path, home)) return false;
  const lowered = path.toLowerCase();
  return SOURCE_SUFFIXES.some((suffix) => lowered.endsWith(suffix));
}

export function isIsolatedWorktree(cwd) {
  const raw = (cwd ?? "").trim();
  if (!raw) return false;
  // Resolved before the segment check, which is the load-bearing part: a
  // substring test on the raw string admits `<root>/.worktrees/../<root>`, the
  // root checkout wearing a worktree's name. Lexical only — the lane worktree is
  // routinely created after this check runs, so requiring it to exist would
  // refuse the command the boundary exists to permit.
  const normalised = normalisePath(raw);
  if (!normalised) return false;
  const withSlash = normalised.endsWith("/") ? normalised : `${normalised}/`;
  return ISOLATED_ROOTS.some((root) => withSlash.includes(root));
}

/** Lexical `normpath`: collapse `.` and `..` without touching the filesystem. */
function normalisePath(input) {
  const absolute = input.startsWith("/");
  const out = [];
  for (const segment of input.split("/")) {
    if (!segment || segment === ".") continue;
    if (segment === "..") {
      if (out.length && out[out.length - 1] !== "..") out.pop();
      else if (!absolute) out.push("..");
      continue;
    }
    out.push(segment);
  }
  const joined = out.join("/");
  const collapsed = absolute ? `/${joined}` : joined;
  // The trailing slash is restored: several markers name a *directory*
  // (`/Documents/handoffs/`), and collapsing removes it.
  return input.endsWith("/") && !collapsed.endsWith("/") ? `${collapsed}/` : collapsed;
}

/**
 * Directories a git command names explicitly, via `-C`, `--git-dir` or
 * `--work-tree`.
 *
 * Judging isolation from the cwd alone is a hole with a very ordinary shape: a
 * lane working inside its own worktree runs `git -C <root> clean -fd`, so the
 * cwd says worktree while the command says root. Whichever path the command
 * names is the path it will act on.
 */
function commandTargetDirs(command) {
  const out = [];
  for (const match of (command ?? "").matchAll(GIT_DIR_FLAG_RE)) {
    const value = (match[1] ?? "").trim().replace(/^['"]|['"]$/g, "");
    if (value) out.push(value);
  }
  return out;
}

/**
 * A destructive command aimed outside a lane worktree.
 *
 * Isolation is judged from every directory the command could act on — the cwd
 * and any path it names — and the checks are a conjunction, so a single named
 * root refuses the call.
 */
export function isRootDestructiveCall(command, { cwd = "" } = {}) {
  if (!isRootDestructive(command)) return false;
  if (isIsolatedWorktree(cwd)) {
    // The cwd is a worktree, but the command may still point elsewhere.
    return commandTargetDirs(command).some((p) => !isIsolatedWorktree(p));
  }
  return true;
}

export function isRootDestructive(command) {
  const text = (command ?? "").trim();
  if (!text) return false;
  return ROOT_DESTRUCTIVE_PATTERNS.some((pattern) => pattern.test(text));
}

export function isProbeCommand(command) {
  const text = (command ?? "").trim();
  if (!text) return false;
  return PROBE_COMMAND_PATTERNS.some((pattern) => pattern.test(text));
}

export function commandTargetsLaneCode(command) {
  return LANE_CODE_RE.test(command ?? "");
}

/** Pull the path and the command out of a host tool input, whatever it is called. */
export function toolCallTargets(input) {
  const args = input ?? {};
  const target = String(
    args.path ?? args.filePath ?? args.file_path ?? args.file ?? args.target ?? "",
  );
  const command = String(args.command ?? args.cmd ?? args.code ?? args.script ?? "");
  return { target, command };
}

/**
 * True for a call that is management, settled locally with no model call.
 *
 * The disqualifiers are applied to the *whole* call before any branch can return
 * True. Ordering them per-branch is the trap: a marker in `target` short-circuits
 * the `or` and the `command` is then never disqualified, so
 * `target='.dispatch/TASK.md'` with `command='cat .worktrees/lane/src/app.py'`
 * reads as management. Neither argument may vouch for the other.
 */
export function isManagementCall(toolName, { target = "", command = "" } = {}, home = "") {
  const name = String(toolName ?? "").trim().toLowerCase();
  if (TOOL_WHITELIST.includes(name)) return true;

  // A command tool is handed its command in `command` by the host, but a caller
  // may pass the same text as `target`. Both spellings are read, so a bypass
  // cannot be had by choosing the other field.
  const text = command || target;

  // A destructive command is never management traffic, whatever else the line
  // mentions; neither is one that reaches into a lane's source. `reflexGate`
  // checks those rules before consulting this function, so the ordering already
  // protects the gate — these keep the predicate honest on its own, for any
  // caller that asks "is this management?" without asking "is this safe?" first.
  if (isRootDestructive(text) || commandTargetsLaneCode(text)) return false;
  if (isRootDestructive(target) || commandTargetsLaneCode(target)) return false;

  if (BUSINESS_CODE_TOOLS.includes(name)) return isWhitelistedPath(target, home);

  if (PROBE_TOOLS.includes(name)) {
    if (isWhitelistedPath(target, home)) return true;
    const plugin = PLUGIN_ENTRY_RE.exec(text);
    if (plugin && WHITELISTED_PLUGIN_COMMANDS.includes(plugin[1])) return true;
    return isWhitelistedPath(text, home) && !SOURCE_TOKEN_RE.test(text);
  }
  return false;
}

/**
 * The corrective steer injected after a refusal.
 *
 * A refusal that only says "no" leaves the model to pick a replacement, and the
 * cheapest replacement is the behaviour just refused. So the steer names the
 * legal next action: wait for worker IPC.
 */
export function reflexSteer(state, { reason = "" } = {}) {
  const waiting = state?.brain?.awaiting_lanes ?? [];
  const who = waiting.length > 0 ? waiting.join(", ") : "the workers";
  const lead = reason.includes("root checkout")
    ? "Dispatch Gate A: the root checkout is not a scratch space. Create or use a " +
      "lane worktree under .worktrees/ (or .herdr/worktrees/) and run destructive " +
      "commands there, or ask the human to authorise a recovery."
    : `Dispatch Gate A: still parked in yield_and_guard, awaiting ${who}.`;
  return (
    `${lead} This tool call was blocked: inspecting or editing a dispatched lane's ` +
    "code is child-work takeover — the lane was dispatched to do it, and doing it " +
    "here burns the tokens the lane is already spending. Do not start new work, do " +
    "not re-check a worker's tests, and do not modify worker-owned files. Proceed " +
    "only on a worker [NOTIFY], a stall alarm, or an explicit human instruction; if " +
    "a lane is genuinely stuck, ask the human rather than taking the work back."
  );
}

/**
 * Judge one orchestrator tool call.
 *
 * @param {any} state the shared dispatch state (for the phase and awaiting lanes)
 * @param {any} input the host's tool input
 * @param {{semantic?: Function, home?: string, cwd?: string}} [options]
 *   `cwd` is the session's working directory, and it is the *only* isolation
 *   signal a host reliably has: a tool event carries no directory of its own, so
 *   without it every destructive command looks like it runs in a root checkout
 *   and none may proceed. That fails closed, which is the right direction, but it
 *   also refuses a lane resetting its own worktree — so the extension supplies it,
 *   and a test asserts the wiring rather than trusting the signature.
 * @returns {{allowed: boolean, verdict: string, reason: string, steer: string}}
 */
export function reflexGate(state, event, options = {}) {
  const toolName = String(event?.toolName ?? "");
  const { target, command } = toolCallTargets(event?.input);
  const home = options.home ?? "";
  const phase = state?.orchestrator_phase ?? "";
  const parked = phase === "yield_and_guard";
  // The event's own cwd wins when the host supplies one; the session's is the
  // fallback. Both are read so a caller cannot accidentally supply neither.
  const cwd = String(event?.cwd ?? options.cwd ?? "");
  // A command tool is handed its command in `command` by the host, but a caller
  // may pass the same text as `target`. Both are read wherever a command is
  // inspected, so a rule cannot be side-stepped by choosing the other argument.
  const shell = command || target;

  const allow = (verdict, reason) => ({ allowed: true, verdict, reason, steer: "" });
  const refuse = (verdict, reason) => ({
    allowed: false,
    verdict,
    reason,
    steer: reflexSteer(state, { reason }),
  });

  // -- layer 2, destructive first -----------------------------------------
  // Ordering is load-bearing, and it is the opposite of "cheapest first". The
  // whitelist is a *bypass*, and a bypass placed ahead of this rule would
  // swallow it: `cat handoffs/x.md && git reset --hard` is a management read
  // followed by the destruction of a root checkout. Deliberately not gated on
  // the tool class — a destructive command is a fact about the *command*, and
  // naming a tool this gate has not heard of must not silence it.
  if (
    isRootDestructiveCall(shell, { cwd }) ||
    isRootDestructiveCall(target, { cwd })
  ) {
    return refuse(
      GateAVerdict.REFUSE_ROOT_DESTRUCTIVE,
      `${shell} destroys uncommitted work, and ${cwd || "the current directory"} is a ` +
        "canonical root checkout rather than an isolated lane worktree. Refused in every " +
        "phase: destructive commands belong in a lane's own worktree.",
    );
  }

  // -- layer 1: local bypass, no socket, no model --------------------------
  if (isManagementCall(toolName, { target, command }, home)) {
    return allow(GateAVerdict.WHITELISTED, "management read: the run's own state or handoffs");
  }

  if (parked && (commandTargetsLaneCode(shell) || commandTargetsLaneCode(target))) {
    return refuse(
      GateAVerdict.REFUSE_CHILD_CODE,
      `${shell || target} names source inside a lane worktree while the orchestrator is ` +
        "parked. The lane owns that code; reaching into it is child-work takeover.",
    );
  }

  // A shell command that inspects a tree is reported as the probe it is, ahead of
  // the generic code rule. The rule stays name-gated because "is this a probe" is
  // a question about a command line, and the tool name is the only signal that
  // the input *is* one. It is phase-independent: a probe is a probe in every
  // phase.
  if (PROBE_TOOLS.includes(toolName) && isProbeCommand(shell)) {
    return refuse(
      GateAVerdict.REFUSE_PROBE,
      `${shell} inspects work owned by a worker lane. The orchestrator dispatched ` +
        "that work; re-doing it is child-work takeover.",
    );
  }

  // Shape, not tool name: a whitelist of tool names has a failure mode with no
  // off switch — rename `read_file` to `read` and the rule silently stops
  // applying. What does not vary is that source is source.
  if (parked && (isBusinessCodePath(target, home) || isBusinessCodePath(shell, home))) {
    return refuse(
      GateAVerdict.REFUSE_CHILD_CODE,
      `the orchestrator is parked in ${phase} and ${target || shell} is business code. ` +
        "That code belongs to a dispatched lane; reading or editing it here is " +
        "child-work takeover, not supervision.",
    );
  }

  // -- layer 3: the genuinely ambiguous call -------------------------------
  // Delegated, never reimplemented. The extension itself passes no delegate (see
  // the module header), so in practice this layer is reached through
  // `dispatch_plugin.py gate`; without one the mechanical layers stand alone,
  // which is the point of having them.
  if (typeof options.semantic === "function") {
    const answer = options.semantic({ toolName, target, command, phase, parked, state });
    const pRole = Number(answer?.pRoleBoundaryViolation ?? 0);
    const pProbe = Number(answer?.pIllegalProbeWhileParked ?? 0);
    if (pRole > THRESHOLD_ROLE_BOUNDARY || pProbe > THRESHOLD_ILLEGAL_PROBE) {
      return refuse(
        GateAVerdict.REFUSE_SEMANTIC,
        `Jev judged this a role boundary violation (p=${pRole.toFixed(2)}) or an illegal ` +
          `probe while parked (p=${pProbe.toFixed(2)}).`,
      );
    }
  }

  return allow(GateAVerdict.ALLOW, "no boundary violation and no probe detected");
}
