"""Closeout Lifecycle Gate — TB-07 / Issue #121.

The failure this exists to prevent
----------------------------------
"Premature Pane Destruction": a feature works, the orchestrator wants the
memory back, it closes the worker pane, and the standard closeout actions —
push the child repo, fast-forward the parent pointer, merge the PR, remove the
worktree — never happen. The next person finds an unpushed branch, a stale
submodule pointer and a leftover worktree.

Destroying the pane is irreversible and it is the *last* step, so it is exactly
the step that must be gated hardest. A worker may be alive, working, or merely
slow; none of those are evidence that closeout is done.

The gate
--------
:func:`evaluate_closeout` runs the five closeout steps in order and returns a
:class:`CloseoutReport`. Every step must pass before
:attr:`CloseoutReport.allowed` is true, and only then may the caller destroy
anything. The order matters and is enforced by :data:`CLOSEOUT_STEPS`:

1. ``handoff_truthful`` — the worker's Done claim survived the Gate C
   truthfulness review (Issue #132). This step is *supplied*, not computed: a
   caller that has not run the reviewer omits it, and the ladder then behaves
   exactly as it did before Gate C existed.
2. ``docs_aligned`` — authoritative docs reconciled with the change;
3. ``child_pushed`` — the child/submodule branch is on the remote;
4. ``parent_pointer_updated`` — the parent gitlink points at that pushed commit;
5. ``pr_merged`` — the PR is merged into the default branch;
6. ``worktree_removed`` — the worktree is physically gone.

A failure stops the ladder. Reporting every remaining step as failed would be
noise, and acting on step 6 while step 3 is untrue is the whole bug.

Verdicts are computed from *facts the caller supplies*, not from shelling out
here. This module stays a pure, testable policy object; a caller resolves each
fact with git or ``gh`` and passes it in. That keeps the gate deterministic and
keeps subprocess concerns out of the decision, which is also what makes the
"simulate an unmerged branch" test case cheap.

Deliberate non-goals (Occam)
---------------------------
This module never runs ``git push``, ``gh pr merge``, ``herdr pane close`` or
``git worktree remove``. It decides whether those are allowed. A gate that
performs the irreversible action cannot be the thing that audits it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

# The canonical closeout order. Index is the execution order, and callers that
# present progress should present it in exactly this sequence.
CLOSEOUT_STEPS: tuple[str, ...] = (
    "docs_aligned",
    "child_pushed",
    "parent_pointer_updated",
    "pr_merged",
    "worktree_removed",
)

# Cleanup authorization proves every prerequisite before physical deletion.
# Final closeout separately proves that deletion actually happened.
PRE_CLEANUP_STEPS: tuple[str, ...] = CLOSEOUT_STEPS[:-1]

# Gate C: the supplied precondition (Issue #132). It is not part of
# :data:`CLOSEOUT_STEPS` because it is not a lifecycle step — it judges whether
# the work was real before the lifecycle begins. A caller that has not run
# ``verify-handoff`` omits it, and the ladder is unchanged.
HANDOFF_TRUTHFUL_STEP = "handoff_truthful"

# Human-readable labels, so a report reads as prose rather than as identifiers.
STEP_LABELS: Dict[str, str] = {
    HANDOFF_TRUTHFUL_STEP: "handoff survived the Gate C truthfulness review",
    "docs_aligned": "authoritative docs aligned with the change",
    "child_pushed": "child/submodule branch pushed to the remote",
    "parent_pointer_updated": "parent gitlink points at the pushed child commit",
    "pr_merged": "PR merged into the default branch",
    "worktree_removed": "worktree physically removed",
}

# Steps that destroy something. `worktree_removed` is the only irreversible one
# and the reason this gate exists; it is gated on every step before it.
DESTRUCTIVE_STEPS = frozenset({"worktree_removed"})

# Step that authorises closing the worker pane.
PANE_CLOSE_GATE_STEP = "worktree_removed"

# Facts a caller may supply per step. A step whose fact is missing is *not*
# assumed true: an absent fact means the step has not been proven, and an
# unproven step must block. This is the fail-loud property from the orchestrator
# lessons doc, applied to closeout.
STEP_FACTS: Dict[str, tuple[str, ...]] = {
    HANDOFF_TRUTHFUL_STEP: ("handoff_verdict", "handoff_accepted", "verified"),
    "docs_aligned": ("docs_reconciled",),
    "child_pushed": ("branch_pushed", "remote_contains_head"),
    "parent_pointer_updated": ("pointer_at_pushed_commit",),
    "pr_merged": ("pr_merged", "default_branch_contains_head"),
    "worktree_removed": ("worktree_absent",),
}

# Facts whose *value* must be one of a fixed set, not merely truthy. The Gate C
# verdict is checked against this before any truthiness test, so a report
# carrying "UNVERIFIED_CLAIMS" is refused and named in the detail rather than
# being waved through by a stale ``accepted: true`` elsewhere in the bundle.
STEP_FACT_VALUES: Dict[str, Dict[str, frozenset]] = {
    HANDOFF_TRUTHFUL_STEP: {"handoff_verdict": frozenset({"ACCEPTED"})},
}


class CloseoutGateError(RuntimeError):
    """Closeout was attempted before the lifecycle gate opened."""


@dataclass
class StepResult:
    """One rung of the closeout ladder."""

    step: str
    passed: bool
    detail: str = ""
    facts: Dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return STEP_LABELS.get(self.step, self.step)

    @property
    def required_facts(self) -> tuple[str, ...]:
        return STEP_FACTS.get(self.step, ())

    def as_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "label": self.label,
            "passed": self.passed,
            "detail": self.detail,
            "facts": dict(self.facts),
        }


@dataclass
class CloseoutReport:
    """The gate's verdict plus the evidence behind it."""

    lane_id: str = ""
    steps: List[StepResult] = field(default_factory=list)
    # Whether the Gate C precondition was evaluated. False means the caller
    # supplied no report, which is *not* the same as a report that passed — see
    # :attr:`truthfulness_not_run`.
    truthfulness_evaluated: bool = False
    purpose: str = "finalize"

    @property
    def truthfulness_not_run(self) -> bool:
        """True when no Gate C report was supplied.

        Kept as its own name because the distinction is the whole point of the
        flag. A caller that never ran ``verify-handoff`` and a caller whose
        review passed produce an identical step list, so a reader of the report
        alone cannot tell "verified" from "never looked". Silence here is the
        failure mode this property exists to make visible.
        """
        return not self.truthfulness_evaluated

    @property
    def blocked_at(self) -> str:
        """First failing step, or "" when the gate is open."""
        for result in self.steps:
            if not result.passed:
                return result.step
        return ""

    @property
    def allowed(self) -> bool:
        """True only when every closeout step is proven."""
        return bool(self.steps) and all(r.passed for r in self.steps)

    @property
    def pane_close_allowed(self) -> bool:
        """Whether the worker pane may be destroyed.

        Identical to :attr:`allowed` today, kept as its own name because this is
        the question an orchestrator actually asks, and collapsing the two
        invites someone to re-derive the rule at the call site.
        """
        return self.allowed and self.purpose == "finalize"

    def result_for(self, step: str) -> Optional[StepResult]:
        for result in self.steps:
            if result.step == step:
                return result
        return None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "lane": self.lane_id,
            "allowed": self.allowed,
            "pane_close_allowed": self.pane_close_allowed,
            "blocked_at": self.blocked_at,
            "truthfulness_evaluated": self.truthfulness_evaluated,
            "purpose": self.purpose,
            "truthfulness_not_run": self.truthfulness_not_run,
            "steps": [s.as_dict() for s in self.steps],
        }

    def render(self) -> str:
        """Human-readable verdict for a terminal or a pane."""
        lines = [f"closeout gate: lane={self.lane_id or '-'}"]
        for result in self.steps:
            mark = "PASS" if result.passed else "BLOCK"
            lines.append(f"  [{mark}] {result.step}: {result.label}")
            if result.detail:
                lines.append(f"         {result.detail}")
        if self.truthfulness_not_run:
            # Stated in both outcomes, not only on failure. A gate that is
            # OPEN without this line reads exactly like one that is open
            # because the work was verified, and those are very different
            # things to be standing on before deleting a worktree.
            lines.append(
                "  [SKIP] " + HANDOFF_TRUTHFUL_STEP + ": not evaluated — no Gate C "
                "report was supplied (run `dispatch_plugin.py verify-handoff` and "
                "pass --handoff-report). The lifecycle steps below are unverified "
                "against the handoff's truthfulness."
            )
        if self.allowed:
            lines.append("  gate OPEN: worktree cleanup and pane close are permitted")
        else:
            lines.append(
                f"  gate CLOSED at {self.blocked_at}: "
                "the worker pane must stay open until this step passes"
            )
        return "\n".join(lines)


def evaluate_step(
    step: str,
    facts: Mapping[str, Any],
    *,
    unmet_detail: str = "",
) -> StepResult:
    """Decide one step from the facts supplied for it.

    Every required fact must be present *and* true. A missing fact is treated as
    unmet rather than skipped, so an incomplete evidence bundle blocks closeout
    instead of silently passing it.
    """
    required = STEP_FACTS.get(step, ())
    if not required:
        return StepResult(step=step, passed=False, detail=f"unknown closeout step {step!r}")

    supplied = dict(facts or {})

    # Value constraints are checked before truthiness, so a report that names a
    # failing verdict is refused *and* the detail quotes that verdict. Checking
    # truthiness first would let a bundle whose other flags are false report only
    # "handoff_accepted is false" and hide what actually went wrong.
    for name, allowed in STEP_FACT_VALUES.get(step, {}).items():
        if name in supplied and supplied[name] not in allowed:
            permitted = ", ".join(sorted(allowed))
            return StepResult(
                step=step,
                passed=False,
                detail=(
                    f"failing: {name} is {supplied[name]!r}, "
                    f"only {permitted} may proceed"
                ),
                facts=supplied,
            )

    missing = [name for name in required if name not in supplied]
    falsey = [
        name for name in required if name in supplied and not bool(supplied[name])
    ]

    if not missing and not falsey:
        return StepResult(step=step, passed=True, facts=supplied)

    if missing:
        detail = unmet_detail or (
            f"unproven: {', '.join(sorted(missing))} not reported "
            "(an unproven step blocks closeout)"
        )
    else:
        detail = unmet_detail or f"failing: {', '.join(sorted(falsey))} is false"

    return StepResult(step=step, passed=False, detail=detail, facts=supplied)


def evaluate_closeout(
    lane_id: str = "",
    evidence: Optional[Mapping[str, Mapping[str, Any]]] = None,
    *,
    steps: Sequence[str] = CLOSEOUT_STEPS,
    stop_at_first_failure: bool = True,
    truthfulness: Optional[Mapping[str, Any]] = None,
    purpose: str = "finalize",
) -> CloseoutReport:
    """Run the closeout ladder and report whether destruction is permitted.

    ``evidence`` maps a step name to its facts, as produced by the caller's git
    and ``gh`` probes. A step absent from ``evidence`` is evaluated as having no
    facts, which fails it.

    ``truthfulness`` supplies the Gate C precondition from Issue #132. When
    present it is evaluated *first*, before any lifecycle step, because pushing
    and merging an unverified lane is the expensive version of the mistake. When
    absent the ladder is exactly :data:`CLOSEOUT_STEPS`, so existing callers are
    unaffected.

    ``stop_at_first_failure`` keeps the report honest about ordering: later
    steps are reported as not reached rather than as independently broken, so
    nobody is told to delete a worktree whose child commit was never pushed.
    """
    report = CloseoutReport(
        lane_id=lane_id,
        truthfulness_evaluated=truthfulness is not None,
        purpose=purpose,
    )
    supplied = dict(evidence or {})
    failure_seen = False

    ladder: List[str] = list(steps)
    if truthfulness is not None:
        ladder.insert(0, HANDOFF_TRUTHFUL_STEP)

    for step in ladder:
        if failure_seen and stop_at_first_failure:
            report.steps.append(
                StepResult(
                    step=step,
                    passed=False,
                    detail="not reached: an earlier closeout step is unmet",
                )
            )
            continue
        if step == HANDOFF_TRUTHFUL_STEP:
            result = evaluate_step(step, truthfulness or {})
        else:
            result = evaluate_step(step, supplied.get(step, {}))
        report.steps.append(result)
        if not result.passed:
            failure_seen = True

    return report


def evaluate_cleanup_authorization(
    lane_id: str = "",
    evidence: Optional[Mapping[str, Mapping[str, Any]]] = None,
    *,
    truthfulness: Optional[Mapping[str, Any]] = None,
    steps: Sequence[str] = PRE_CLEANUP_STEPS,
) -> CloseoutReport:
    """Prove deletion prerequisites without pretending deletion already happened."""
    return evaluate_closeout(
        lane_id,
        evidence,
        steps=steps,
        truthfulness=truthfulness,
        purpose="cleanup",
    )


def assert_closeout_allowed(
    lane_id: str,
    evidence: Optional[Mapping[str, Mapping[str, Any]]] = None,
    *,
    truthfulness: Optional[Mapping[str, Any]] = None,
) -> CloseoutReport:
    """Gate for a destructive action: return the report, or raise.

    The single entry point an orchestrator should use before ``herdr pane
    close`` or ``git worktree remove``. Refusing loudly is the point — a silent
    skip here is how the premature-destruction lesson repeats.
    """
    report = evaluate_closeout(lane_id, evidence, truthfulness=truthfulness)
    if not report.allowed:
        raise CloseoutGateError(report.render())
    return report


# A fully-satisfied evidence bundle. Useful as a default fixture and as the
# documented shape callers must produce.
SATISFIED_EVIDENCE: Dict[str, Dict[str, Any]] = {
    "docs_aligned": {"docs_reconciled": True},
    "child_pushed": {"branch_pushed": True, "remote_contains_head": True},
    "parent_pointer_updated": {"pointer_at_pushed_commit": True},
    "pr_merged": {"pr_merged": True, "default_branch_contains_head": True},
    "worktree_removed": {"worktree_absent": True},
}