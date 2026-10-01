"""Unified dispatch bus — the single atomic command for a lane dispatch.

What it replaces
----------------
Dispatching a lane was six manual steps: ``lint`` the contract, ``claim`` the
worktree, rename the pane, mint a timestamp, assemble a ``[NOTIFY]`` envelope,
flush the brain state, then send. Any one could be skipped, and skipping any of
them was invisible until closeout — a lane running with no state entry, a pane
still called ``worker-3``, a handoff referenced by a filename nobody generated.

This module fuses them so the omissions are no longer expressible.

Atomicity is the design constraint, not a feature
-------------------------------------------------
The contract for a dispatch is: **if any pre-flight gate refuses, nothing may be
renamed, nothing written to the state file, and nothing delivered.** That is not
achievable by validating inside a sequence of mutations, because the mutation
that ran before the failure has already happened.

So the work is split in two:

- :meth:`DispatchPlan.plan` is **pure**. It runs every gate, mints the
  timestamp, and assembles the envelope. It raises before producing a value, so
  a refusal provably cannot have mutated anything.
- :meth:`DispatchPlan.commit` performs the three mutations, in the order that
  degrades most safely: state first, rename second, delivery last. Delivery is
  last because it is the only one the lane can observe.

No shelling out, no string commands. The bus produces values and the plugin
turns them into argv arrays, so there is no shell for an orchestrator to quote
its way out of.

Exit codes are distinct on purpose: ``1`` means the contract is malformed,
``2`` means a rule refused (collision, bad lane name, delivery blocked). An
orchestrator can tell "fix your task file" from "the lane is unsafe".
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import orchestrator_state as brain
import prompt_protocol as promptproto

# Parameter derivation lives in its own module because it needs to shell out
# (git, Herdr) and this one holds a hard no-shell invariant.
import dispatch_derive as derive

# Lane naming convention, enforced by the issue: <wave>-<lane>-<slug>.
# `1-2-sysctl`, `1-3-dispatch`, `1-4-research`. `research-agy` is the canonical
# counter-example -- it carries no lane coordinates, so nothing can tell which
# wave it belongs to or who owns it.
LANE_NAME_PATTERN = r"^[0-9]+-[0-9]+-[a-z0-9_-]+$"
LANE_NAME_RE = re.compile(LANE_NAME_PATTERN)

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
HANDOFF_DIR = "~/Documents/handoffs"

def rename_pane(pane_id: str, label: str) -> None:
    """Rename a Herdr pane.

    Presentation only: a pane label is not agent lifecycle state, so this does
    not cross the single-writer line.

    The client is imported lazily and resolved at call time, which is what makes
    this stubbable in tests. An earlier version had the plugin rebind this
    module global on every call, which silently overwrote any test recorder --
    and would have clobbered anything else that wanted to wrap it.
    """
    if not pane_id:
        return
    try:
        import herdr_client as herdr
    except ImportError:  # pragma: no cover - the plugin always ships it
        return
    try:
        herdr.run_herdr(["pane", "rename", pane_id, label])
    except herdr.HerdrError:
        # Renaming is presentation. A lane that cannot be renamed is still
        # dispatched and recorded; the state file is the source of truth.
        pass


class DispatchRefused(RuntimeError):
    """A pre-flight gate refused the dispatch.

    ``exit_code`` distinguishes a malformed contract (1) from a rule refusal (2).
    """

    exit_code = 2

    def __init__(self, message: str, *, exit_code: Optional[int] = None) -> None:
        super().__init__(message)
        # Default to the *class* value. Hardcoding 2 here would set an instance
        # attribute that shadows ContractError.exit_code = 1, and every contract
        # failure would then report itself as a rule refusal.
        if exit_code is not None:
            self.exit_code = exit_code


class InvalidLaneNameError(DispatchRefused):
    """``--lane-name`` does not match the project convention."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"lane name {name!r} violates the project convention {LANE_NAME_PATTERN}.\n"
            "Expected <wave>-<lane>-<slug>, e.g. 1-2-sysctl, 1-3-dispatch, "
            "1-4-research. A bare slug like 'research-agy' carries no lane "
            "coordinates, so nothing can tell which wave owns it."
        )
        self.name = name


class ContractError(DispatchRefused):
    """The task contract failed its mechanical lint."""

    exit_code = 1


def make_timestamp(now: Optional[float] = None) -> str:
    """Second-level ``YYYYMMDD_HHMMSS``.

    Second-level, never day-only: two lanes finishing on the same day would
    otherwise collide on one handoff filename and silently overwrite each other.
    """
    return time.strftime(TIMESTAMP_FORMAT, time.localtime(now))


# Re-exported so the plugin and the tests have one import for the naming rules:
# the pattern, the coordinates it implies, and the handoff path it forms.
lane_from_name = derive.lane_from_name


def validate_lane_name(name: str) -> str:
    """Return ``name`` if it conforms, else raise.

    Also used by :func:`handoff_path`, so a nonconforming name cannot reach a
    handoff filename even by another route.
    """
    if not LANE_NAME_RE.match(name or ""):
        raise InvalidLaneNameError(name)
    return name


def handoff_path(lane_name: str, timestamp: str) -> str:
    """The one true handoff location for this lane and dispatch.

    Always fully qualified and always timestamped. A bare filename is not
    accepted: a worker reporting ``done.md`` is a handoff nobody can find.
    """
    validate_lane_name(lane_name)
    return f"{HANDOFF_DIR}/{lane_name}-handoff-{timestamp}.md"


def build_envelope(
    signature: str,
    done: str,
    handoff: str,
    target: str,
    *,
    highlights: Sequence[str] = (),
    risks: Sequence[str] = (),
) -> str:
    """Assemble the worker's ``[NOTIFY]`` reply envelope.

    Reuses the prompt gate's formatter so the bus cannot produce a differently
    shaped report than everything else in the system. Real ``0x0A`` newlines by
    construction, since the text is built in Python rather than quoted in a
    shell — which is the whole point of this command.
    """
    return promptproto.build_notify(
        signature, done, handoff, target, highlights=highlights, risks=risks
    )


@dataclass
class DispatchPlan:
    """Everything a dispatch needs, computed before anything is touched."""

    repo: Path
    task: Path
    lane: str
    lane_name: str
    target: str
    signature: str
    timestamp: str
    handoff: str
    envelope: str
    worktree: str = ""
    branch: str = ""
    highlights: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    # What the bus derived, and any caller input it discarded. Returned rather
    # than printed: planning has no side effects, so the *caller* decides where
    # a note goes. An orchestrator that cannot see what was derived on its
    # behalf cannot tell a derived value from a typo.
    notes: List[str] = field(default_factory=list)

    # -- planning --------------------------------------------------------

    @classmethod
    def plan(
        cls,
        *,
        repo: Path,
        task: Path,
        lane_name: str,
        target: str,
        signature: str,
        lane: str = "",
        worktree: str = "",
        branch: str = "",
        highlights: Sequence[str] = (),
        risks: Sequence[str] = (),
        timestamp: Optional[str] = None,
        pane_lookup: Optional[Callable[[str], str]] = None,
        branch_reader: Optional[Callable[[str], str]] = None,
    ) -> "DispatchPlan":
        """Run every gate and compute every value. Raises on any refusal.

        Pure: reads files, the state document and the target pane, mutates
        none, renames nothing and sends nothing. That is what makes
        :meth:`commit` safe to run only on a value that exists.

        Six parameters became four (Issue #136). ``lane``, ``worktree``,
        ``branch``, ``highlights`` and ``risks`` are derived from the lane
        name, the target pane and the task contract — and each is refused
        outright when it cannot be derived, because an empty value here is not
        "nothing to record", it is a gate that silently did not run.
        """
        notes: List[str] = []

        # Gate 1 — the lane name. Cheapest, and a bad name would otherwise
        # become a handoff filename.
        validate_lane_name(lane_name)

        # Derivation 1 — the lane coordinates. `--lane-name` is the single
        # source; a stale `--lane` is reported and overridden rather than
        # honoured, so the two can never disagree about which lane is running.
        lane = _derive_lane(lane_name, lane, notes)

        # Derivation 1b — the report signature. Derived from the *resolved* lane
        # id, leading with it, because the brain parks on lane ids: a signature
        # that named only the pane would resolve to a lane the brain is not
        # waiting on, and `awaiting_lanes` would never empty. See
        # notify.laneFromSignature, which reads both forms.
        signature = signature or f"{lane}_{target}"

        # Gate 2 — the contract. ContractError carries exit_code 1 so the
        # caller can distinguish "your file is wrong" from "the lane is unsafe".
        _lint_contract(task)

        # Derivation 2 — the report halves, from the contract's own sections.
        # Blank overrides are dropped before this point: an empty string is
        # truthy as a list element, so `[""]` would look supplied, suppress the
        # derivation, and put an empty `- ` bullet in the worker's report.
        highlights = [h for h in highlights if (h or "").strip()]
        risks = [r for r in risks if (r or "").strip()]
        if not highlights or not risks:
            parsed_highlights, parsed_risks = _derive_report_items(task)
            highlights = highlights or parsed_highlights
            risks = risks or parsed_risks

        # Derivation 3 — the placement, from the pane that will do the work.
        worktree, branch = _derive_placement(
            target,
            worktree=worktree,
            branch=branch,
            notes=notes,
            pane_lookup=pane_lookup,
            branch_reader=branch_reader,
        )

        # Gate 3 — the claim. A placement is always present by now — either
        # derived or supplied — so this gate always runs, and an empty pair is
        # refused rather than read as "this lane claims nothing".
        _claim(repo, lane, worktree=worktree, branch=branch)

        stamp = timestamp or make_timestamp()
        handoff = handoff_path(lane_name, stamp)

        envelope = build_envelope(
            signature,
            f"Lane dispatched: {lane_name}. Read {task.name}, execute, then report via the notify command below.",
            handoff,
            target,
            highlights=list(highlights),
            risks=list(risks),
        )

        # Gate 4 — the envelope must itself satisfy the prompt contract, or the
        # bus would enqueue a message its own gate refuses to send.
        promptproto.assert_prompt_compliant(envelope)

        return cls(
            repo=repo,
            task=task,
            lane=lane,
            lane_name=lane_name,
            target=target,
            signature=signature,
            timestamp=stamp,
            handoff=handoff,
            envelope=envelope,
            worktree=worktree,
            branch=branch,
            highlights=list(highlights),
            risks=list(risks),
            notes=notes,
        )

    # -- state -----------------------------------------------------------

    def state_payload(self) -> Dict[str, Any]:
        """The lane and pane entries this dispatch should persist."""
        lane_entry: Dict[str, Any] = {
            "lane": self.lane,
            "name": self.lane_name,
            "pane_id": self.target,
            "task": str(self.task),
            "handoff": self.handoff,
            "dispatched_unix_ms": brain.now_unix_ms(),
        }
        if self.worktree:
            lane_entry["worktree"] = self.worktree
        if self.branch:
            lane_entry["branch"] = self.branch
        return lane_entry

    # -- commit ----------------------------------------------------------

    def commit(self) -> Dict[str, Any]:
        """Perform the mutations, in least-observable-first order.

        1. brain state — the record must exist before anyone acts on it;
        2. pane rename — cosmetic, and recoverable;
        3. delivery — last, because it is the only step the lane can observe.

        Each step is independent, so a failure in step 3 leaves a correct state
        file rather than a lane that was told to start and has no record.
        """
        state_path = brain.state_path(self.repo)
        state = brain.load(state_path)

        entry = self.state_payload()
        entry["status"] = "working"
        state.setdefault("lanes", {})[self.lane] = {
            **state.get("lanes", {}).get(self.lane, {}),
            **entry,
        }
        state["active_panes"] = brain.default_state()["active_panes"] | {
            "lanes": {
                **state.get("active_panes", {}).get("lanes", {}),
                self.lane: {"pane": self.target, "lane_name": self.lane_name},
            }
        }
        # A dispatch is what the orchestrator then waits on. The brain machine
        # only permits contract -> topology -> yield_and_guard, so walk the legal
        # path rather than jumping: forcing the jump would either raise
        # BrainPhaseError or leave a brain state claiming a phase it never
        # legitimately reached.
        _advance_to_parked(state, [self.lane])
        brain.save(state_path, state)

        rename_pane(self.target, self.lane_name)

        return state


# --------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------


# Legal prefixes into the park, per orchestrator_state.BRAIN_TRANSITIONS.
_PARK_PATHS: tuple[tuple[str, ...], ...] = (
    ("contract", "topology", "yield_and_guard"),
    ("topology", "yield_and_guard"),
    ("yield_and_guard",),
)


def _advance_to_parked(state: Dict[str, Any], awaiting: Sequence[str]) -> Dict[str, Any]:
    """Walk the brain into ``yield_and_guard`` along a legal transition path.

    ``advance`` refuses illegal jumps by design, and it is right to: a brain
    that claims a phase it never traversed is worse than one that reports where
    it really is. So the bus follows the state machine instead of overriding it.

    ``awaiting`` is the lane just dispatched. It has to be recorded, not
    re-derived: parking with the *previous* wait list produces a brain that
    believes it is waiting on nothing while a worker is running.
    """
    current = brain._safe_str(state.get("orchestrator_phase")) or brain.DEFAULT_BRAIN_PHASE
    for path in _PARK_PATHS:
        if path[0] == current:
            for phase in path[1:]:
                brain.advance(state, phase, reason=f"awaiting lane dispatch")
            brain.park(state, list(awaiting))
            return state
    raise DispatchRefused(
        f"cannot park the brain from phase {current!r}; no legal transition path "
        f"to yield_and_guard. Park it manually, or dispatch from a fresh run."
    )


def _derive_lane(lane_name: str, override: str, notes: List[str]) -> str:
    """Resolve the lane id, with ``--lane-name`` as the single source of truth.

    A supplied ``--lane`` that disagrees is reported and discarded. Silently
    honouring it would keep the exact inconsistency the merge removes; silently
    ignoring it would leave the caller believing the wrong lane ran.
    """
    derived = _deriving(lane_from_name, lane_name)
    supplied = (override or "").strip()
    if supplied and supplied != derived:
        notes.append(
            f"--lane {supplied!r} disagrees with --lane-name {lane_name!r}; "
            f"using the lane name's coordinates {derived!r}"
        )
    return derived


def _derive_report_items(task: Path) -> tuple[List[str], List[str]]:
    """Parse the contract's own report sections."""
    return _deriving(derive.report_items_from_task, task)


def _derive_placement(
    target: str,
    *,
    worktree: str,
    branch: str,
    notes: List[str],
    pane_lookup: Optional[Callable[[str], str]] = None,
    branch_reader: Optional[Callable[[str], str]] = None,
) -> tuple[str, str]:
    """Resolve the worktree/branch pair, deriving whatever was not supplied.

    An explicit override wins, because someone who knows the worktree better
    than a probe does is entitled to say so. It may not supply only half of the
    pair: ``(worktree, "")`` would reach the claim gate as a lane that claims a
    directory but no branch, which is the interleaved-commits failure with one
    leg removed.

    An override is still *validated*. Skipping validation on the supplied path
    would leave a documented remedy for a refused derivation — "pass the values
    explicitly" — that reproduces the refusal instead of fixing it: a pane on a
    detached HEAD yields the literal branch ``HEAD``, which passes straight
    through and isolates nothing.
    """
    supplied_worktree = (worktree or "").strip()
    supplied_branch = (branch or "").strip()

    if supplied_worktree and supplied_branch:
        # Both were named, so there is nothing to probe — but the pair is
        # still held to the same rules as a derived one.
        return (
            _deriving(derive.normalise_worktree, supplied_worktree),
            _deriving(derive.checked_branch, supplied_branch, supplied_worktree),
        )

    if supplied_worktree:
        # The worktree was named, so the branch is read from *that* directory.
        # Reading it from the pane instead would describe a different tree than
        # the one being claimed: a pair that looks valid and isolates nothing.
        resolved_worktree = _deriving(derive.normalise_worktree, supplied_worktree)
        resolved_branch = _deriving(derive.branch_at, resolved_worktree, reader=branch_reader)
        notes.append(f"branch derived from {resolved_worktree}: {resolved_branch}")
        return resolved_worktree, resolved_branch

    # Nothing was supplied: both halves come from the target pane, so they are
    # guaranteed to describe the same tree.
    placement = _deriving(
        derive.derive_placement,
        target,
        pane_lookup=pane_lookup,
        branch_reader=branch_reader,
    )
    notes.append(
        f"worktree derived from pane {target}: {placement.worktree}; "
        f"branch: {placement.branch}"
    )
    if supplied_branch and supplied_branch != placement.branch:
        notes.append(
            f"--branch {supplied_branch!r} disagrees with the branch checked out "
            f"in {placement.worktree} ({placement.branch!r}); using the branch "
            "the lane's own worktree is on"
        )
    return placement.worktree, placement.branch


def _deriving(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a derivation, re-raising its refusal as a rule refusal (exit 2).

    The distinction matters to an orchestrator: exit 1 means "fix your task
    file", exit 2 means "this lane is unsafe as the world stands". A derivation
    that failed is the second kind, and must not be reported as the first.
    """
    try:
        return fn(*args, **kwargs)
    except derive.DerivationRefused as exc:
        raise DispatchRefused(f"parameter derivation refused the dispatch:\n{exc}") from exc


def _lint_contract(task: Path) -> None:
    """Run ``dispatch.py lint``'s rules over the task file.

    Delegates to the skill engine rather than reimplementing the rules, so the
    bus cannot drift from the linter it claims to enforce. Import is lazy: the
    skill lives outside the plugin and the plugin must stay importable alone.
    """
    import importlib.util

    engine = Path(__file__).resolve().parents[3] / (
        "agent-skills/local/global/dispatch/scripts/dispatch.py"
    )
    if not engine.is_file():
        raise ContractError(f"dispatch engine not found at {engine}")

    module_name = "dispatch_engine_for_bus"
    spec = importlib.util.spec_from_file_location(module_name, engine)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before executing. The engine defines a @dataclass, and dataclass
    # resolves its own module through sys.modules at class-creation time -- so
    # without this the exec dies with
    # "AttributeError: 'NoneType' object has no attribute '__dict__'".
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        try:
            module.lint_task_contract(task)
        except module.TaskContractError as exc:
            raise ContractError(f"contract lint refused the dispatch:\n{exc}") from exc
    finally:
        sys.modules.pop(module_name, None)


def _claim(repo: Path, lane: str, *, worktree: str, branch: str) -> None:
    """Refuse if a live lane already holds this worktree or branch.

    An empty pair is refused here rather than treated as "nothing to claim".
    The claim gate skips a lane with no worktree and no branch, so an empty pair
    is a gate that did not run — and the only way one reaches this point is a
    derivation that failed silently. Making it a refusal means that failure has
    to be loud.
    """
    import lane_isolation as isolation

    if not (worktree.strip() or branch.strip()):
        raise DispatchRefused(
            f"lane {lane!r} has no worktree and no branch to claim. "
            "1 Lane = 1 Worktree = 1 Branch has no exception for a lane that "
            "could not be placed; fix the pane or pass both explicitly."
        )

    state = brain.load(brain.state_path(repo))
    try:
        isolation.claim_lane(
            state.get("lanes") or {}, lane, worktree=worktree, branch=branch
        )
    except isolation.LaneCollisionError as exc:
        raise DispatchRefused(
            f"claim gate refused the dispatch:\n{exc}"
        ) from exc


# --------------------------------------------------------------------------
# Receipt
# --------------------------------------------------------------------------


def receipt(plan: DispatchPlan) -> str:
    """A dense one-screen summary of what was dispatched."""
    lines = [
        f"dispatch: lane {plan.lane} ({plan.lane_name}) -> {plan.target}",
        f"  task     : {plan.task}",
        f"  handoff  : {plan.handoff}",
        f"  timestamp: {plan.timestamp}",
    ]
    if plan.worktree:
        lines.append(f"  worktree : {plan.worktree}")
    if plan.branch:
        lines.append(f"  branch   : {plan.branch}")
    # Derived values and overridden overrides are both worth showing: one is
    # how the orchestrator learns what the bus decided on its behalf, the other
    # is how it learns its own input was discarded.
    for note in plan.notes:
        lines.append(f"  derived  : {note}")
    lines.append("  brain    : yield_and_guard")
    return "\n".join(lines)
