"""Orchestrator permission gate — TB-09.

What it is for
---------------
The orchestrator is the one participant in a dispatch run that can ruin a lane
without touching a lane's files. Its documented job is to split work, dispatch,
park, and wake. Everything that burns tokens while a worker runs — probing
`git status`, re-reading child code to "check" it, polling worker panes — is
work the *worker* was dispatched to do. Done by the orchestrator, it produces the
false-busywork loop from orchestrator lesson 1 and child-work takeover from the
governance doc.

None of that is enforceable by asking the model to resist a prompt. It is
enforceable here, because every orchestrator action is a named step and the
brain phase is already recorded in the shared state file.

The whitelist
-------------
:data:`PHASE_ALLOWANCES` maps each of the seven brain phases to the actions
permitted there. Anything not listed is refused. Two rules cut across the whole
table:

- **Probes are never allowed.** ``probe_*`` is refused in every phase, including
  the ones where curiosity looks harmless, because a probe whose result arrives
  is indistinguishable from one whose result justifies acting. Refusing the
  class removes the judgement call.
- **The park is a hard stop.** In ``yield_and_guard`` only wake signals, status
  reads and harvest pass. An orchestrator that starts "just checking" here has
  stopped waiting, and the wait is the thing the workers depend on.

Judges, does not act
---------------------
Like every other gate in this plugin, this module decides and refuses. It never
runs the action it refused, never transitions the brain on the caller's behalf,
and never records that the attempt happened on its own. Recording is the
caller's call — a gate that keeps its own audit trail can be accused of writing
to the state file to justify itself.

Gate A: the PreToolUse reflex gate (Issue #133)
----------------------------------------------
The matrix above polices a *named orchestrator step*. A tool call is not a named
step. The orchestrator can reach straight into a worker's file with ``read_file``
and never appear in :data:`PHASE_ALLOWANCES` at all — which is exactly how
"just checking" turns into child-work takeover.

Gate A closes that at the tool boundary, in three layers ordered by cost:

1. **Fast whitelist bypass.** Pure management reads — ``todo``, the state file,
   the handoffs directory, the orchestrator's own task contract — are settled
   locally and never open a socket. The park produces a great deal of legitimate
   management traffic, and a model call per reminder would cost more than it
   decides.
2. **Mechanical interception.** Two classes are facts, not judgments, and block
   without asking anything: a business-code read while parked, and a destructive
   workspace command aimed at a canonical root checkout. The second one is an
   incident written down — ``git reset --hard`` in a root checkout is not a probe
   to be debated, it is unrecoverable work, so it is refused in *every* phase and
   only inside a lane worktree.
3. **Jev semantics.** What is left is genuinely a question of role: is this call
   a boundary violation, and is it an illegal probe while parked. Those go to
   TypeSafe Jev as two Noul questions and block over 0.40.

The destructive check runs *before* the whitelist, and that inversion is
load-bearing rather than incidental. The whitelist is a bypass, and a bypass
placed ahead of a mechanical rule swallows it: ``cat handoffs/x.md && git reset
--hard`` is a management read followed by the destruction of a root checkout. Each
layer is individually correct, so no test of one layer catches this — only the
composition does.

Like every other gate here, Gate A judges. It never performs the call it
refused, and it never writes the state file.
"""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

DEFAULT_TYPESAFE_API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_JEV_MODEL = "jev-latest"
HEURISTIC_MODEL = "heuristic-fallback"
WHITELIST_MODEL = "whitelist"
MECHANICAL_MODEL = "mechanical"

# The seven brain phases. Mirrors orchestrator_state.BRAIN_PHASES; repeated here
# so this module stays importable on its own and the matrix can be checked
# against the real list by a test.
BRAIN_PHASES: tuple[str, ...] = (
    "contract",
    "topology",
    "yield_and_guard",
    "synthesis",
    "decision",
    "human_gate",
    "closed",
)

# Actions permitted in every phase. Deliberately tiny: read-only, no side
# effects, and useful precisely when something has gone wrong.
ALWAYS_ALLOWED: frozenset[str] = frozenset({"status", "read_state", "harvest", "render_board"})

# Actions that inspect the work a worker owns. Refused everywhere.
FORBIDDEN_PROBES: frozenset[str] = frozenset(
    {
        "probe_git_status",
        "probe_child_code",
        "probe_worker_pane",
        "probe_child_tests",
        "read_child_source",
        "rerun_child_tests",
    }
)

# Per-phase whitelist. Each entry is the set of actions legal in that phase.
PHASE_ALLOWANCES: Dict[str, frozenset[str]] = {
    "contract": frozenset({"lint_task_contract", "write_spec", "ask_human"}),
    "topology": frozenset(
        {"plan_lanes", "claim_lane", "create_worktree", "dispatch_lane", "gate_prompt"}
    ),
    # The park. Wake signals and reads only — see the module docstring.
    "yield_and_guard": frozenset(
        {"wake", "wait_lanes", "notify_human", "stall_alarm"}
    ),
    "synthesis": frozenset({"reconcile_facts", "read_handoffs", "compare_lanes"}),
    "decision": frozenset(
        {"rework_decision", "spawn_skeptic", "request_human_authorization"}
    ),
    # Human authorisation is a human action, never an automatic one.
    "human_gate": frozenset({"await_human", "read_human_decision"}),
    "closed": frozenset({"read_state"}),
}

# The action that leaves the park, and the signals that may legitimately end it.
#
# Kept apart on purpose: WAKE_SIGNALS holds *signal names*, while WAKE_ACTION is
# the orchestrator step. Comparing the action against the signal set would make
# every supplied signal meaningless, because "wake" is not one of the three.
WAKE_ACTION = "wake"
WAKE_SIGNALS: frozenset[str] = frozenset({"notify", "stall_alarm", "human"})


class IllegalOrchestratorActionError(RuntimeError):
    """The orchestrator attempted an action its brain phase does not permit."""

    def __init__(
        self,
        message: str,
        *,
        action: str = "",
        phase: str = "",
        allowed: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.action = action
        self.phase = phase
        self.allowed = tuple(allowed)


@dataclass
class GuardVerdict:
    """The gate's answer for one (phase, action) pair."""

    allowed: bool
    action: str
    phase: str
    reason: str = ""
    allowed_actions: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "action": self.action,
            "phase": self.phase,
            "reason": self.reason,
            "allowed_actions": list(self.allowed_actions),
        }

    def render(self) -> str:
        if self.allowed:
            return f"orchestrator guard: ALLOW {self.action} in {self.phase}"
        lines = [
            f"orchestrator guard: REFUSE {self.action} in {self.phase}",
            f"  {self.reason}",
        ]
        if self.allowed_actions:
            lines.append("  permitted here: " + ", ".join(self.allowed_actions))
        return "\n".join(lines)


def allowed_in(phase: str) -> frozenset[str]:
    """Everything legal in ``phase``, including the always-allowed set."""
    return PHASE_ALLOWANCES.get(phase, frozenset()) | ALWAYS_ALLOWED


def is_probe(action: str) -> bool:
    """True for any action that inspects work a worker owns.

    Matches the whole ``probe_*`` family, not just the two named in the issue,
    so a newly invented probe name is refused by default rather than by
    remembering to add it to a list.
    """
    return action.startswith("probe_") or action in FORBIDDEN_PROBES


class OrchestratorGuard:
    """Mechanical enforcement of orchestrator behaviour per brain phase.

    Usage::

        guard = OrchestratorGuard(phase)
        guard.check("claim_lane")                 # raises on refusal
        guard.check("probe_git_status")           # IllegalOrchestratorActionError
        guard.allowed_actions()                   # what *is* legal here
    """

    def __init__(self, phase: str, *, wake_signal: str = "") -> None:
        self.phase = phase
        self.wake_signal = wake_signal
        if phase not in BRAIN_PHASES:
            raise ValueError(
                f"unknown brain phase {phase!r}; expected one of {', '.join(BRAIN_PHASES)}"
            )

    # -- queries ---------------------------------------------------------

    def allowed_actions(self) -> List[str]:
        return sorted(allowed_in(self.phase))

    def permits(self, action: str) -> bool:
        return self.evaluate(action).allowed

    # -- evaluation ------------------------------------------------------

    def evaluate(self, action: str) -> GuardVerdict:
        """Decide without raising. Callers that must not block use this."""
        allowed = sorted(allowed_in(self.phase))

        # Probes are refused before anything else, so the reason reported is the
        # real one even in a phase where the action is absent anyway.
        if is_probe(action):
            return GuardVerdict(
                allowed=False,
                action=action,
                phase=self.phase,
                reason=(
                    f"{action!r} inspects work owned by a worker lane. The "
                    "orchestrator dispatched that work; re-doing it is child-work "
                    "takeover and burns tokens the worker is already spending."
                ),
                allowed_actions=allowed,
            )

        if action == WAKE_ACTION:
            if self.phase != "yield_and_guard":
                return GuardVerdict(
                    allowed=False,
                    action=action,
                    phase=self.phase,
                    reason=(
                        f"{action!r} is a park wake signal, but the orchestrator is "
                        f"in {self.phase!r}, not parked."
                    ),
                    allowed_actions=allowed,
                )
            # A supplied signal must be one the protocol recognises. A todo
            # reminder is explicitly not a wake signal: treating any string as
            # one would reopen the false-busywork loop this gate exists to close.
            if self.wake_signal and self.wake_signal not in WAKE_SIGNALS:
                return GuardVerdict(
                    allowed=False,
                    action=action,
                    phase=self.phase,
                    reason=(
                        f"{self.wake_signal!r} is not a wake signal; the orchestrator "
                        f"stays parked. Recognised: {', '.join(sorted(WAKE_SIGNALS))}."
                    ),
                    allowed_actions=allowed,
                )
            return GuardVerdict(True, action, self.phase, allowed_actions=allowed)

        if action in allowed_in(self.phase):
            return GuardVerdict(True, action, self.phase, allowed_actions=allowed)

        # `human_gate` gets its own message: crossing it is a Human Gate action,
        # not merely an out-of-phase one.
        if self.phase == "human_gate" and action in {
            "git_push",
            "merge_pr",
            "delete_branch",
            "remove_worktree",
            "close_pane",
        }:
            return GuardVerdict(
                allowed=False,
                action=action,
                phase=self.phase,
                reason=(
                    f"{action!r} is irreversible publication. It is permitted only "
                    "with explicit human authorisation, never by an automatic path."
                ),
                allowed_actions=allowed,
            )

        return GuardVerdict(
            allowed=False,
            action=action,
            phase=self.phase,
            reason=(
                f"{action!r} is not permitted while the orchestrator brain is in "
                f"{self.phase!r}."
            ),
            allowed_actions=allowed,
        )

    # -- enforcement -----------------------------------------------------

    def check(self, action: str) -> GuardVerdict:
        """Gate entry point: return the verdict, or raise."""
        verdict = self.evaluate(action)
        if not verdict.allowed:
            raise IllegalOrchestratorActionError(
                verdict.render(), action=action, phase=self.phase,
                allowed=verdict.allowed_actions,
            )
        return verdict


def check_action(phase: str, action: str, *, wake_signal: str = "") -> GuardVerdict:
    """Functional shorthand for a single check."""
    return OrchestratorGuard(phase, wake_signal=wake_signal).check(action)


def matrix() -> List[Dict[str, Any]]:
    """The whole whitelist as data, for documentation and for tests."""
    return [
        {
            "phase": phase,
            "allowed": sorted(allowed_in(phase)),
            "forbidden_probes": sorted(FORBIDDEN_PROBES),
        }
        for phase in BRAIN_PHASES
    ]


# ==========================================================================
# Gate A (Issue #133) — the PreToolUse reflex gate
# ==========================================================================

# Tools that touch files. Named as the issue names them, plus the write-side
# spellings a host may use; matching the class rather than an exact list is what
# keeps a renamed tool from walking past the gate.
BUSINESS_CODE_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "view_file",
        "write_file",
        "replace_file_content",
        "edit_file",
        "create_file",
        "apply_patch",
    }
)

# Tools that run a command. Every one of them can read a worker's tree, so they
# are classified by the command text rather than the tool name.
PROBE_TOOLS: frozenset[str] = frozenset({"bash", "shell", "python", "exec", "command"})

# Pure management tools. No target, no tree, no judgment: these are the calls the
# orchestrator makes *about* the run rather than *inside* it.
TOOL_WHITELIST: frozenset[str] = frozenset(
    {"todo", "todowrite", "todowrite_tool", "read_todos", "set_todos"}
)

# Paths the orchestrator may read at any time. The state file is how it knows it
# is parked; the handoffs directory is how it collects results; the task contract
# is its own instructions. Reading any of them is the job, not a probe.
WHITELIST_PATH_MARKERS: tuple[str, ...] = (
    "ORCHESTRATOR_STATE.json",
    "CHECKPOINT.json",
    "/Documents/handoffs/",
    ".dispatch_task_",
    "/.dispatch/",
)

# The plugin's own read-only commands, invoked through bash. Matched on the
# subcommand so `dispatch_plugin.py status` passes while an arbitrary script of
# the same name would not — the allowlist is a closed set of verbs, not a prefix.
_WHITELISTED_PLUGIN_COMMANDS: frozenset[str] = frozenset(
    {"status", "render_board", "harvest", "board", "gate", "guard", "startup"}
)
_PLUGIN_ENTRY_RE = re.compile(r"dispatch_plugin\.py\s+([a-z_]+)")

# Source extensions. A path with one of these is business code unless it also
# carries a whitelist marker, which is the whole of the parked-state read rule.
_SOURCE_SUFFIXES: tuple[str, ...] = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".rs", ".go", ".rb", ".java",
    ".kt", ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".sh", ".zsh", ".bash",
)

# Worktree isolation roots. A destructive command is only safe inside one of
# these; anywhere else it is aimed at a checkout someone works in directly.
_ISOLATED_ROOTS: tuple[str, ...] = ("/.worktrees/", "/.herdr/worktrees/", "/worktrees/")

# Commands that destroy uncommitted work or rewrite history. `git reset --hard`
# and `git clean -fd` are the two that lose a day; the rest either lose one or
# publish one, so they are in the same class.
#
# Every git pattern tolerates global flags between `git` and the subcommand,
# because `git -C <root> clean -fd` is the same destruction with a detour, and a
# pattern demanding `git clean` adjacently does not see it at all.
_GIT = r"\bgit\b[^|;&|]*?\s+"
_ROOT_DESTRUCTIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(_GIT + r"reset\b(?![^|;&]*--soft)(?![^|;&]*--mixed)(?![^|;&]*--merge)"),
    re.compile(_GIT + r"clean\b[^|;&]*-[a-z]*f"),
    re.compile(_GIT + r"checkout\s+(--\s+)?\."),
    re.compile(_GIT + r"restore\b[^|;&]*\s+\."),
    # `git switch --discard-changes` is the modern spelling of `checkout .`.
    re.compile(_GIT + r"switch\b[^|;&]*--discard-changes"),
    re.compile(_GIT + r"stash\s+(drop|clear)"),
    re.compile(_GIT + r"push\b[^|;&]*(--force|-f)\b"),
    # Removing a worktree deletes a directory a peer agent may be running tests
    # in — orchestrator lesson 2, and the reason one-lane-one-worktree exists.
    re.compile(_GIT + r"worktree\s+remove\b"),
    re.compile(_GIT + r"branch\s+-D\b"),
    # `rm` with a recursive or force flag, in either spelling. A gate that knows
    # only `-rf` is one refactor from failing, and `--recursive --force` is what
    # a script written to avoid short flags produces.
    re.compile(r"\brm\b(?=[^|;&]*\s-{1,2}(?:[a-zA-Z]*r[a-zA-Z]*|recursive|force))"),
)

# The directory a git command names with `-C`, `--git-dir` or `--work-tree`.
# Captured so the isolation check can judge the command's real target rather than
# only the cwd it happens to run from.
_GIT_DIR_FLAG_RE = re.compile(
    r"(?:^|(?<=[\s;&|]))(?:-C|--git-dir|--work-tree)(?:[=\s]+|\s*)(\S+)"
)

# Commands that inspect work a worker owns. Matches the whole family rather than
# a list of spellings, for the reason `is_probe` documents: an unregistered name
# must be refused by default.
#
# The single-letter and short names are anchored on a command-position boundary
# rather than a plain word boundary: `\bfd\b` also matches the `-fd` in
# `git clean -fd`, and a probe pattern that fires on its own destructive-
# command's flags would refuse every `git clean` — including one inside a lane's
# own worktree, which is exactly the operation the isolation boundary permits.
_CMD_POS = r"(?:^|(?<=[\s;&|(]))"
_PROBE_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgit\s+(status|diff|log|show|blame|ls-files|whatchanged)\b"),
    re.compile(r"\b(pytest|vitest|jest|mocha|cargo\s+(?:test|build|check)|go\s+test)\b"),
    re.compile(r"\b(npm|pnpm|yarn|bun)\s+(?:run\s+)?(test|build|check|lint)\b"),
    re.compile(r"\b(make\s+(check|test|ci)|ruff|mypy|eslint|tsc)\b"),
    re.compile(_CMD_POS + r"(cat|head|tail|less|grep|rg|ag|awk)\b"),
    re.compile(_CMD_POS + r"(ls|find|fd|stat|wc|du|file)\b"),
    re.compile(_CMD_POS + r"diff\b"),
)

# Thresholds from Issue #133. Both block strictly above 0.40.
THRESHOLD_ROLE_BOUNDARY = 0.40
THRESHOLD_ILLEGAL_PROBE = 0.40

# Bounded context. The orchestrator's tool call is a short string; the bound is
# there so a pasted transcript cannot turn a per-call judgment into a large one.
MAX_TOOL_CALL_CHARS = 1200


class GateAVerdict(str, Enum):
    """Why Gate A allowed or refused one tool call."""

    WHITELISTED = "WHITELISTED"
    ALLOW = "ALLOW"
    REFUSE_CHILD_CODE = "REFUSE_CHILD_CODE"
    REFUSE_PROBE = "REFUSE_PROBE"
    REFUSE_ROOT_DESTRUCTIVE = "REFUSE_ROOT_DESTRUCTIVE"
    REFUSE_SEMANTIC = "REFUSE_SEMANTIC"


@dataclass
class GateAReport:
    """One tool call's verdict, with the evidence behind it.

    ``model`` records which layer decided, and is the fastest way to tell a
    deterministic refusal from a judged one in a log.
    """

    allowed: bool
    verdict: GateAVerdict
    tool: str
    phase: str
    reason: str = ""
    target: str = ""
    command: str = ""
    p_role_boundary_violation: float = 0.0
    p_illegal_probe_while_parked: float = 0.0
    model: str = MECHANICAL_MODEL
    corrective_steer: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "verdict": self.verdict.value,
            "tool": self.tool,
            "phase": self.phase,
            "reason": self.reason,
            "target": self.target,
            "command": self.command,
            "p_role_boundary_violation": round(self.p_role_boundary_violation, 4),
            "p_illegal_probe_while_parked": round(self.p_illegal_probe_while_parked, 4),
            "model": self.model,
            "corrective_steer": self.corrective_steer,
        }

    def render(self) -> str:
        head = "gate A: ALLOW" if self.allowed else "gate A: REFUSE"
        lines = [f"{head} {self.tool} in {self.phase} [{self.verdict.value}]"]
        if self.reason:
            lines.append(f"  {self.reason}")
        if not self.allowed and self.corrective_steer:
            lines.append(f"  steer: {self.corrective_steer}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Layer 1 — the fast local bypass
# --------------------------------------------------------------------------


def _expand(text: str) -> str:
    """Expand a leading ``~`` so a ``~/...`` path compares against the markers.

    The markers stay machine-independent — ``/Documents/handoffs/`` rather than
    a per-user absolute path — which is what lets the TS half hold a
    byte-identical list, and what keeps the public template free of any one
    machine's home directory. Only the home prefix is substituted, and only at
    the start: a ``~`` in the middle of a path is a literal character.
    """
    raw = (text or "").strip()
    if not raw or not raw.startswith("~"):
        return raw
    home = str(Path.home())
    if raw == "~":
        return home
    if not raw.startswith("~/"):
        return raw
    # A home that cannot be resolved stays "~" rather than becoming a bogus
    # prefix, so the comparison simply fails instead of matching the wrong path.
    if home in ("", "~"):
        return raw
    return f"{home}/{raw[2:]}"


def is_management_call(
    tool: str,
    *,
    target: str = "",
    command: str = "",
) -> bool:
    """True for a call that is management, settled locally with no model call.

    Kept a pure function of the call, not of the phase: whether reading the state
    file is legitimate does not depend on which phase asked.

    The disqualifiers are applied to the *whole* call before any branch can
    return True. Ordering them per-branch is the trap: a marker in ``target``
    short-circuits the ``or`` and the ``command`` is never disqualified, so
    ``target='~/Documents/handoffs/x.md'`` with ``command='cat .worktrees/lane/src/app.py'``
    reads as management. Neither argument may vouch for the other.
    """
    name = (tool or "").strip().lower()
    if name in TOOL_WHITELIST:
        return True

    # A command tool is handed its command in `command` by the host, but a caller
    # may pass the same text as `target`. Both spellings are read, so a bypass
    # cannot be had by choosing the other field.
    text = command or target

    # A destructive command is never management traffic, whatever else the line
    # mentions; neither is one that reaches into a lane's source. `evaluate`
    # checks those rules before consulting this function, so the ordering already
    # protects the gate — these keep the predicate honest on its own, for any
    # caller that asks "is this management?" without asking "is this safe?" first.
    if is_root_destructive(text) or command_targets_lane_code(text):
        return False
    if is_root_destructive(target) or command_targets_lane_code(target):
        return False

    if name in BUSINESS_CODE_TOOLS:
        return _is_whitelisted_path(target)

    if name in PROBE_TOOLS:
        return _is_whitelisted_path(target) or _is_whitelisted_command(text)

    return False


def _is_whitelisted_path(target: str) -> bool:
    """Whether a path names the run's own management surface.

    The markers are a substring list, so the path is *normalised* before the
    comparison. Without that, ``.dispatch/../src/app.py`` contains the marker and
    the marker is what the whitelist is looking for — the whitelist would then
    vouch for a read of a lane's source, which is the one thing it exists to
    prevent. A whitelist that can be walked out of with ``..`` is not one.
    """
    path = _expand(target)
    if not path:
        return False
    return any(marker in _normalise(path) for marker in WHITELIST_PATH_MARKERS)


def _normalise(path: str) -> str:
    """Lexical ``normpath``: collapse ``.`` and ``..`` without touching the disk.

    Lexical rather than resolving, because the path being judged routinely does
    not exist yet — a lane worktree is often created after the check runs — and a
    whitelist or boundary that required the file to exist would be useless.
    """
    try:
        # The trailing slash is restored: several markers name a *directory*
        # (`/Documents/handoffs/`), and normpath drops it.
        normalised = os.path.normpath(path)
    except (TypeError, ValueError):  # pragma: no cover - malformed input
        return path
    return normalised + "/" if path.endswith("/") and not normalised.endswith("/") else normalised


def _is_whitelisted_command(command: str) -> bool:
    """True for a shell command that only reads the run's own management surface.

    Two shapes qualify, and neither admits a third:

    - the plugin's read-only verbs, matched on the entry script against a closed
      set of subcommands;
    - a read whose argument is a whitelist path — ``cat ~/Documents/handoffs/x.md``
      is how a harvest is actually performed, so a marker check on the command
      text is what stops that being mistaken for a probe.

    A command that *also* names source inside a lane worktree is never whitelisted,
    whatever else it mentions. Otherwise `cat handoff.md && cat .worktrees/lane/x.py`
    would buy a free pass by leading with a legitimate path.
    """
    text = (command or "").strip()
    if not text:
        return False
    match = _PLUGIN_ENTRY_RE.search(text)
    if match and match.group(1) in _WHITELISTED_PLUGIN_COMMANDS:
        return True

    return _is_whitelisted_path(text) and not _SOURCE_TOKEN_RE.search(text)


# --------------------------------------------------------------------------
# Layer 2 — mechanical facts
# --------------------------------------------------------------------------


def is_business_code_path(target: str) -> bool:
    """True when a path names source the orchestrator did not dispatch.

    A source extension is the signal. The whitelist markers are checked first so
    a state file that happens to end in ``.json`` is never mistaken for code, and
    a configuration file the orchestrator legitimately consults while parked is
    not a takeover.
    """
    path = _expand(target)
    if not path:
        return False
    if _is_whitelisted_path(path):
        return False
    lowered = path.lower()
    if lowered.endswith(_SOURCE_SUFFIXES):
        return True
    return False


def is_isolated_worktree(cwd: str) -> bool:
    """True when a path really is inside a worktree isolation root.

    This is the whole of the workspace-isolation boundary. A lane may destroy its
    own scratch tree; a canonical root checkout may not be destroyed by anyone,
    because there is no second copy of what is uncommitted in it.

    The path is *resolved* before the segment check, which is the load-bearing
    part. A substring test on the raw string admits
    ``<root>/.worktrees/../<root>`` — the root checkout wearing a worktree's name
    — and that is precisely the shape a determined (or merely confused) caller
    produces. Lexical normalisation, not resolution, is used on purpose: a lane
    worktree is routinely created after the check runs, and requiring the
    directory to exist would refuse exactly the command it exists to permit.
    """
    path = (cwd or "").strip()
    if not path:
        return False
    # `normpath` collapses `..` without touching the filesystem. Expand `~` too,
    # since a lane worktree is commonly named from `$HOME`.
    expanded = os.path.expanduser(path)
    try:
        normalised = os.path.normpath(expanded)
    except (TypeError, ValueError):  # pragma: no cover - malformed input
        return False
    if not normalised.endswith("/"):
        normalised += "/"
    return any(root in normalised for root in _ISOLATED_ROOTS)


def is_root_destructive(command: str) -> bool:
    """True for a command that destroys uncommitted work or rewrites history."""
    text = (command or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _ROOT_DESTRUCTIVE_PATTERNS)


def is_probe_command(command: str) -> bool:
    """True for a shell command that inspects a tree rather than driving the bus."""
    text = (command or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _PROBE_COMMAND_PATTERNS)


# A source path appearing as a token in a shell command. Matches an isolated lane
# worktree specifically: `cat src/app.py` in the orchestrator's own checkout is
# an ordinary read, while `cat .worktrees/<lane>/src/app.py` is reaching into a
# lane's tree, which is the thing the park forbids.
_LANE_CODE_RE = re.compile(
    r"(?:\.worktrees|\.herdr/worktrees|worktrees)/[^\s'\";|&]*"
    r"[^\s'\";|&]*\.(?:py|ts|tsx|js|jsx|mjs|rs|go|rb|java|kt|swift|c|cc|cpp|h|hpp|sh|zsh|bash)\b"
)

# Any source filename token, wherever it appears. Used only to disqualify a
# command from the whitelist, so it is deliberately broad.
_SOURCE_TOKEN_RE = re.compile(
    r"[^\s'\";|&]*\.(?:py|ts|tsx|js|jsx|mjs|rs|go|rb|java|kt|swift|c|cc|cpp|h|hpp|sh|zsh|bash)\b"
)


def command_targets_lane_code(command: str) -> bool:
    """True when a shell command names source inside a lane worktree."""
    return bool(_LANE_CODE_RE.search(command or ""))


def command_addresses_lane(command: str, *, awaiting: Sequence[str] = ()) -> bool:
    """True when a command names a lane by id or by the word "lane".

    A parked orchestrator that types a lane's identifier is reaching for that
    lane. It is a weaker signal than a probe — a legitimate synthesis-phase
    reconciliation also names lanes — so it only carries weight while parked.
    """
    text = (command or "").lower()
    if not text:
        return False
    if any(lane and lane.lower() in text for lane in awaiting):
        return True
    return bool(re.search(r"\blanes?\b", text))


def _command_target_dirs(command: str) -> List[str]:
    """Directories a git command names explicitly, via ``-C`` or ``--git-dir``.

    Judging isolation from the cwd alone is a hole with a very ordinary shape:
    a lane working inside its own worktree runs ``git -C <root> clean -fd`` and
    the cwd says worktree while the command says root. Whichever path the command
    names is the path it will act on, so both are collected and the *most
    privileged* answer wins — one named root is enough to refuse.
    """
    found: List[str] = []
    for match in _GIT_DIR_FLAG_RE.finditer(command or ""):
        value = match.group(1).strip().strip("'\"")
        if value:
            found.append(value)
    return found


def is_root_destructive_call(command: str, *, cwd: str = "") -> bool:
    """A destructive command aimed outside a lane worktree.

    ``git reset --hard`` in a canonical root checkout loses whatever was
    uncommitted there, and no lane can undo that. Inside ``.worktrees/`` the same
    command is a lane resetting its own scratch tree, which is the invariant
    working as intended.

    Isolation is judged from every directory the command could act on — the cwd
    and any path it names with ``-C`` / ``--git-dir`` — and the check is a
    conjunction, so a single named root refuses the call.
    """
    if not is_root_destructive(command):
        return False
    if is_isolated_worktree(cwd):
        # The cwd is a worktree, but the command may still point elsewhere.
        return any(not is_isolated_worktree(p) for p in _command_target_dirs(command))
    return True


def corrective_steer(phase: str, *, awaiting: Sequence[str] = ()) -> str:
    """The message injected into the orchestrator's session after a refusal.

    A refusal that only says "no" leaves the model to guess what to do instead,
    and the cheapest guess is the behaviour the gate just refused. So the steer
    names the legal next action: wait for worker IPC.
    """
    who = ", ".join(awaiting) if awaiting else "the workers"
    return (
        f"Dispatch Gate A: still parked in {phase}, awaiting {who}. This tool call "
        "was blocked because inspecting or editing a dispatched lane's code is "
        "child-work takeover — the lane was dispatched to do it, and doing it here "
        "burns the tokens the lane is already spending. Do not start new work, do "
        "not re-check a worker's tests, and do not modify worker-owned files. "
        "Proceed only on a worker [NOTIFY], a stall alarm, or an explicit human "
        "instruction; if a lane is genuinely stuck, ask the human rather than "
        "taking the work back."
    )


# --------------------------------------------------------------------------
# Layer 3 — Jev
# --------------------------------------------------------------------------


def resolve_api_key(key: Optional[str] = None) -> str:
    """Find the TypeSafe key.

    An explicit value wins, including an explicit empty string, which is the
    documented way to force the offline path without touching the environment.
    """
    if key is not None:
        return key.strip()
    resolved = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if resolved:
        return resolved
    omp_env = Path.home() / ".omp" / "agent" / ".env"
    if omp_env.is_file():
        try:
            for line in omp_env.read_text(encoding="utf-8").splitlines():
                if line.startswith("TYPESAFE_API_KEY="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            pass
    return ""


def _build_gate_a_questions() -> Dict[str, Any]:
    """The two semantic questions, batched into one request.

    Phrased as descriptions of the *call*, not as accusations about the caller.
    An accusation makes an innocuous call score high, and a gate that blocks
    correct work is worse than no gate — the same calibration failure Gate C
    recorded, so the framing is deliberate rather than incidental.
    """
    return {
        "is_role_boundary_violation": {
            "type": "noul",
            "instructions": (
                "Is this tool call the orchestrator doing a dispatched worker's job? "
                "The orchestrator's role is to split work, dispatch lanes, park, and "
                "wake. Reading, editing, or verifying the source code inside a lane's "
                "worktree is the worker's role."
            ),
            "criteria": {
                "true": (
                    "The call reads, edits, or runs checks against a lane's own source "
                    "or tests — the lane owns that work"
                ),
                "false": (
                    "The call concerns the dispatch run itself: the state file, task "
                    "contracts, handoffs, the lane board, or scheduling"
                ),
            },
        },
        "is_illegal_probe_while_parked": {
            "type": "noul",
            "instructions": (
                "The orchestrator is deliberately parked in yield_and_guard, waiting "
                "for a worker's completion report. Is this call an unauthorised probe "
                "of a running lane's state while parked?"
            ),
            "criteria": {
                "true": (
                    "The call checks a running lane's git state, test output, or files "
                    "while the orchestrator is supposed to be waiting"
                ),
                "false": (
                    "The call does not inspect a running lane: it is a management read, "
                    "or a deliberate decision the park does not forbid"
                ),
            },
        },
    }


def _ask_jev(
    state: Mapping[str, Any],
    *,
    key: str,
    timeout: float = 8.0,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """One batched round trip. Returns ``None`` on any failure.

    ``None`` means "no judgment", not "no problem": the caller falls back to
    heuristics rather than reading an unanswered question as a pass.
    """
    endpoint = api_url or os.environ.get("TYPESAFE_API_URL") or DEFAULT_TYPESAFE_API_URL
    target_model = model or os.environ.get("TYPESAFE_MODEL") or DEFAULT_JEV_MODEL
    body = {
        "state": dict(state.get("state_payload") or {}),
        "model": target_model,
        "questions": _build_gate_a_questions(),
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "mac-bootstrap-gate-a/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None
    if not isinstance(parsed, Mapping):
        return None
    answers = parsed.get("answers")
    if not isinstance(answers, Mapping):
        return None

    p_role, role_usable = _noul(answers, "is_role_boundary_violation")
    p_probe, probe_usable = _noul(answers, "is_illegal_probe_while_parked")
    if not (role_usable and probe_usable):
        # A half-answer is no answer. Returning ``None`` routes the caller to the
        # offline heuristics, which is the fail-closed direction.
        return None
    return {
        "p_role_boundary_violation": p_role,
        "p_illegal_probe_while_parked": p_probe,
        "model": _sanitise_model(parsed.get("model"), target_model),
    }


def _noul(answers: Mapping[str, Any], name: str) -> Tuple[float, bool]:
    """Read one Noul probability. Returns ``(value, usable)``.

    The flag exists because ``0.0`` is not a safe sentinel. A genuine 0.0 is a
    legitimate answer — the model is confident this is not a violation — but so is
    every failure to obtain one: ``float("high")`` raises, ``None`` raises, a
    missing key returns nothing, ``NaN`` compares False against every threshold.
    Collapse those and a garbage response converts a refusal into a pass, which
    is the one direction a security gate must never fail in.

    The value is also clamped to a finite range in ``[0, 1]``. A probability is
    bounded, and one that is not is not usable evidence.
    """
    raw = answers.get(name)
    if isinstance(raw, Mapping):
        raw = raw.get("noul")
    if raw is None or isinstance(raw, bool):
        return 0.0, False
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return 0.0, False
    if not math.isfinite(number):
        return 0.0, False
    return min(1.0, max(0.0, number)), True


def _sanitise_model(name: Any, fallback: str) -> str:
    """Keep the endpoint's model name inert.

    It is echoed into reports, the corrective steer and the logs, so a name
    carrying a newline would let a remote endpoint append lines of its own to
    whatever reads them. Bounded to one short token.
    """
    text = str(name or "").strip().splitlines()[0].strip() if str(name or "").strip() else ""
    text = re.sub(r"[^A-Za-z0-9._+-]", "", text)
    return text[:64] or fallback


def _heuristic_scores(
    *,
    tool: str,
    target: str,
    command: str,
    phase: str,
    awaiting: Sequence[str] = (),
) -> Dict[str, float]:
    """Offline probabilities for the two semantic questions.

    A regex is good at one thing here: noticing the shape of a takeover. So the
    offline layer mirrors the mechanical rules and reports the *conclusion* the
    mechanical layer would have reached anyway, with the parked flag folded in.

    A parked call that names a lane is treated as a probe even when no probe verb
    is present — ``herdr agent get`` on a running lane is the same reflex as
    ``git status``, spelled differently. Outside the park the score drops below
    the block line, because reading source in synthesis is legitimate
    reconciliation and a gate that refuses correct work is worse than no gate.
    """
    parked = phase == "yield_and_guard"
    # Shape, not tool name, for the same reason the mechanical layers work that
    # way: an unrecognised tool name must not be a way to be unjudged.
    source_read = is_business_code_path(target) or is_business_code_path(command)
    probe = is_probe_command(command) or is_probe_command(target)
    addresses_lane = command_addresses_lane(
        command, awaiting=awaiting
    ) or command_addresses_lane(target, awaiting=awaiting)

    p_role = 0.0
    if source_read:
        p_role = 0.78 if parked else 0.30
    if parked and (
        addresses_lane
        or command_targets_lane_code(command)
        or command_targets_lane_code(target)
    ):
        p_role = max(p_role, 0.72)

    p_probe = 0.0
    if probe and parked:
        p_probe = 0.72
    elif parked and addresses_lane:
        p_probe = max(p_probe, 0.68)
    elif probe:
        p_probe = 0.30
    return {"is_role_boundary_violation": p_role, "is_illegal_probe_while_parked": p_probe}


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------


class ToolCallGate:
    """PreToolUse interception for the orchestrator session.

    Usage::

        gate = ToolCallGate("yield_and_guard")
        gate.check("read_file", target=".worktrees/lane/src/app.py")  # raises
        gate.check("todo")                                            # allow
    """

    def __init__(
        self,
        phase: str,
        *,
        wake_signal: str = "",
        awaiting: Sequence[str] = (),
        key: Optional[str] = None,
        timeout: float = 8.0,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        use_jev: bool = True,
    ) -> None:
        if phase not in BRAIN_PHASES:
            raise ValueError(
                f"unknown brain phase {phase!r}; expected one of {', '.join(BRAIN_PHASES)}"
            )
        self.phase = phase
        self.wake_signal = wake_signal
        self.awaiting = tuple(awaiting)
        self.key = key
        self.timeout = timeout
        self.api_url = api_url
        self.model = model
        # Heuristics are the baseline, not the exception. The mechanical layers
        # already settle the important cases; a model call is opt-in so a
        # miscalibrated judgment cannot start refusing correct work by default.
        self.use_jev = use_jev

    def evaluate(
        self,
        tool: str,
        *,
        target: str = "",
        command: str = "",
        cwd: str = "",
    ) -> GateAReport:
        """Decide without raising. Callers that must not block use this."""
        name = (tool or "").strip()
        parked = self.phase == "yield_and_guard"
        # A command tool is handed its command in `command` by the host, but a
        # caller may pass the same text as `target`. Both are read wherever a
        # command is inspected, so the rules cannot be side-stepped by choosing
        # the other argument.
        shell = command or target

        # -- layer 2, destructive first ------------------------------------
        # Ordering is load-bearing, and it is the opposite of "cheapest first".
        # The whitelist is a *bypass*, and a bypass placed ahead of these two
        # rules would swallow them: `cat handoffs/x.md && git reset --hard` is a
        # management read followed by the destruction of a root checkout, and
        # reading the leading path first would wave the whole line through. A
        # destructive command is a fact, and a fact is never something a bypass
        # may carry.
        if is_root_destructive_call(shell, cwd=cwd) or is_root_destructive_call(
            target, cwd=cwd
        ):
            return GateAReport(
                allowed=False,
                verdict=GateAVerdict.REFUSE_ROOT_DESTRUCTIVE,
                tool=name,
                phase=self.phase,
                reason=(
                    f"{shell or target!r} destroys uncommitted work, and "
                    f"{cwd or 'the current directory'!r} "
                    "is a canonical root checkout rather than an isolated lane worktree. "
                    "There is no second copy of what is uncommitted there, so this is "
                    "refused in every phase. Destructive commands belong in a lane's own "
                    "worktree under .worktrees/ or .herdr/worktrees/."
                ),
                target=target,
                command=command,
                model=MECHANICAL_MODEL,
                corrective_steer=(
                    "Dispatch Gate A: the root checkout is not a scratch space. Create or "
                    "use a lane worktree under .worktrees/ (or .herdr/worktrees/) and run "
                    "destructive commands there, or ask the human to authorise a recovery."
                ),
            )

        # -- layer 1: local bypass, no socket, no model --------------------
        if is_management_call(name, target=target, command=command):
            return GateAReport(
                allowed=True,
                verdict=GateAVerdict.WHITELISTED,
                tool=name,
                phase=self.phase,
                reason="management read: the run's own state, contract or handoffs",
                target=target,
                command=command,
                model=WHITELIST_MODEL,
            )

        if parked:
            # Both parked rules are decided by the *shape* of what the call names,
            # not by the tool's name. A whitelist of tool names has a failure mode
            # with no off switch: rename `read_file` to `read`, add a host-specific
            # wrapper, or pass an empty name, and the rule silently stops
            # applying. What does not vary is that a lane worktree holds code the
            # orchestrator was not dispatched to touch.
            if command_targets_lane_code(shell) or command_targets_lane_code(target):
                return GateAReport(
                    allowed=False,
                    verdict=GateAVerdict.REFUSE_CHILD_CODE,
                    tool=name,
                    phase=self.phase,
                    reason=(
                        f"{(shell or target)!r} names source inside a lane worktree while the "
                        f"orchestrator is parked in {self.phase!r}. The lane owns that code; "
                        "reaching into it is child-work takeover, not supervision."
                    ),
                    target=target,
                    command=command,
                    model=MECHANICAL_MODEL,
                    corrective_steer=corrective_steer(self.phase, awaiting=self.awaiting),
                )

        # A shell command that inspects a tree is reported as the probe it is,
        # ahead of the generic code rule. The rule stays name-gated because "is
        # this a probe" is a question about a command line, and the tool name is
        # the only signal that the input *is* one. It is phase-independent: a
        # probe is a probe in every phase.
        if name in PROBE_TOOLS and is_probe_command(shell):
            return GateAReport(
                allowed=False,
                verdict=GateAVerdict.REFUSE_PROBE,
                tool=name,
                phase=self.phase,
                reason=(
                    f"{shell!r} inspects work owned by a worker lane. The orchestrator "
                    "dispatched that work; re-doing it is child-work takeover and burns "
                    "tokens the worker is already spending."
                ),
                target=target,
                command=command,
                model=MECHANICAL_MODEL,
                corrective_steer=corrective_steer(self.phase, awaiting=self.awaiting),
            )

        if parked and (is_business_code_path(target) or is_business_code_path(shell)):
            return GateAReport(
                allowed=False,
                verdict=GateAVerdict.REFUSE_CHILD_CODE,
                tool=name,
                phase=self.phase,
                reason=(
                    f"the orchestrator is parked in {self.phase!r} and "
                    f"{(target or shell)!r} is business code. That code belongs to a "
                    "dispatched lane; reading or editing it here is child-work takeover, "
                    "not supervision."
                ),
                target=target,
                command=command,
                model=MECHANICAL_MODEL,
                corrective_steer=corrective_steer(self.phase, awaiting=self.awaiting),
            )

        # -- layer 3: the genuinely ambiguous call -------------------------
        state_payload = {
            "tool": name,
            "target": (target or "")[:MAX_TOOL_CALL_CHARS],
            "command": (command or "")[:MAX_TOOL_CALL_CHARS],
            "phase": self.phase,
            "parked": parked,
            "awaiting_lanes": list(self.awaiting),
        }
        answers = self._semantic_answer(state_payload)
        p_role = answers["is_role_boundary_violation"]
        p_probe = answers["is_illegal_probe_while_parked"]
        actual_model = answers["model"]

        if p_role > THRESHOLD_ROLE_BOUNDARY or p_probe > THRESHOLD_ILLEGAL_PROBE:
            return GateAReport(
                allowed=False,
                verdict=GateAVerdict.REFUSE_SEMANTIC,
                tool=name,
                phase=self.phase,
                reason=(
                    f"Jev judged this a role boundary violation "
                    f"(p={p_role:.2f} > {THRESHOLD_ROLE_BOUNDARY}) or an illegal probe "
                    f"while parked (p={p_probe:.2f} > {THRESHOLD_ILLEGAL_PROBE})"
                ),
                target=target,
                command=command,
                p_role_boundary_violation=p_role,
                p_illegal_probe_while_parked=p_probe,
                model=actual_model,
                corrective_steer=corrective_steer(self.phase, awaiting=self.awaiting),
            )

        return GateAReport(
            allowed=True,
            verdict=GateAVerdict.ALLOW,
            tool=name,
            phase=self.phase,
            reason="no boundary violation and no probe detected",
            target=target,
            command=command,
            p_role_boundary_violation=p_role,
            p_illegal_probe_while_parked=p_probe,
            model=actual_model,
        )

    def _semantic_answer(self, state_payload: Mapping[str, Any]) -> Dict[str, Any]:
        """The Jev answer, or the offline heuristic's."""
        key = resolve_api_key(self.key) if self.use_jev else ""
        if key:
            answered = _ask_jev(
                {"state_payload": state_payload},
                key=key,
                timeout=self.timeout,
                api_url=self.api_url,
                model=self.model,
            )
            if answered is not None:
                return {
                    "is_role_boundary_violation": answered["p_role_boundary_violation"],
                    "is_illegal_probe_while_parked": answered["p_illegal_probe_while_parked"],
                    "model": answered["model"],
                }
        scores = _heuristic_scores(
            tool=state_payload.get("tool", ""),
            target=state_payload.get("target", ""),
            command=state_payload.get("command", ""),
            phase=state_payload.get("phase", self.phase),
            awaiting=state_payload.get("awaiting_lanes") or (),
        )
        return {**scores, "model": HEURISTIC_MODEL}

    def check(
        self,
        tool: str,
        *,
        target: str = "",
        command: str = "",
        cwd: str = "",
    ) -> GateAReport:
        """Gate entry point: return the verdict, or raise."""
        report = self.evaluate(tool, target=target, command=command, cwd=cwd)
        if not report.allowed:
            raise IllegalOrchestratorActionError(
                report.render(),
                action=f"{tool}:{target or command}",
                phase=self.phase,
                allowed=sorted(allowed_in(self.phase)),
            )
        return report


def check_tool_call(
    tool: str,
    *,
    target: str = "",
    command: str = "",
    cwd: str = "",
    phase: str = "yield_and_guard",
    awaiting: Sequence[str] = (),
    key: Optional[str] = None,
    timeout: float = 8.0,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
    use_jev: bool = True,
) -> GateAReport:
    """Functional shorthand for one tool call."""
    gate = ToolCallGate(
        phase,
        awaiting=awaiting,
        key=key,
        timeout=timeout,
        api_url=api_url,
        model=model,
        use_jev=use_jev,
    )
    return gate.evaluate(tool, target=target, command=command, cwd=cwd)