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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

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