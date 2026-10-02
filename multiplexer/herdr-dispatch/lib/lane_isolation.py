"""One-Lane-One-Worktree-One-Branch invariant — TB-06.

Why this exists
---------------
The invariant doc (`docs/ONE_WORKTREE_PER_LANE_INVARIANT.md`) records what
happens when two interactive agents share one worktree:

1. a lane that finishes first mechanically merges the *other* lane's untested
   WIP commits into production;
2. the lane that finishes first then runs worktree cleanup and physically
   deletes the directory its peer is still running tests in;
3. both lanes hold the submodule dirty, so each one's `worktree-init` gate
   refuses the other's, and the pair deadlocks.

None of those symptoms name the cause, which is why the rule needs to be a
check rather than prose in a skill file.

What this enforces
------------------
A claim is a triple ``(lane_id, worktree_path, branch)``. Before a lane is
dispatched, :func:`claim_lane` proves the worktree and the branch are both
unclaimed by a *live* lane. Two failures are refusals, not warnings:

- the same worktree claimed by two lanes (the stomping case);
- the same branch claimed by two lanes (commits would interleave).

Completed or explicitly released lanes do not hold a claim, so a re-run of the
same lane id after a clean closeout is legal. A lane reclaiming *its own*
worktree and branch is a no-op rather than a collision, because the single
writer for that lane is still the same agent.

Deliberate non-goals (Occam)
---------------------------
This module does not create worktrees, does not shell out to ``git worktree``,
and does not own a registry file. It reads the lanes already recorded in the
shared state document and answers one question: *may this lane claim this
worktree and branch?*
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

# Only verified terminal/cleanup states release a physical claim.
# Loss of observability (orphaned / unknown / recovery_required) is not proof
# that the worker stopped using its worktree.
RELEASED_STATUSES = frozenset({"closed", "released", "cleaned"})


class LaneCollisionError(RuntimeError):
    """A lane tried to claim a worktree or branch another live lane holds.

    Raised, never logged-and-continued: sharing a worktree silently corrupts
    two lanes at once, and the corruption surfaces far from its cause.
    """

    def __init__(
        self,
        message: str,
        *,
        lane_id: str = "",
        resource: str = "",
        holder: str = "",
        requested: str = "",
    ) -> None:
        super().__init__(message)
        self.lane_id = lane_id
        self.resource = resource  # "worktree" or "branch"
        self.holder = holder  # the lane that already holds it
        self.requested = requested


@dataclass(frozen=True)
class LaneClaim:
    """One lane's physical isolation claim."""

    lane_id: str
    worktree: str
    branch: str
    status: str = ""

    @property
    def released(self) -> bool:
        return self.status.strip().lower() in RELEASED_STATUSES


@dataclass
class ClaimAudit:
    """Outcome of an isolation check, for reporting and for tests.

    ``ok`` is the gate decision. ``claims`` is retained so a caller can render
    the whole isolation picture without re-reading the state document.
    """

    lane_id: str
    ok: bool
    worktree: str = ""
    branch: str = ""
    existing: List[LaneClaim] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "lane": self.lane_id,
            "ok": self.ok,
            "worktree": self.worktree,
            "branch": self.branch,
            "existing_claims": [
                {"lane": c.lane_id, "worktree": c.worktree, "branch": c.branch}
                for c in self.existing
            ],
            "violations": list(self.violations),
        }


def normalise_path(raw: str) -> str:
    """Canonicalise a worktree path for comparison.

    Two lanes naming the same directory differently (``./wt`` vs an absolute
    path, a trailing slash, a symlinked temp dir) must still collide, so
    comparison happens on the resolved path rather than the raw string. A path
    that cannot be resolved falls back to an absolute lexically-normalised form
    instead of raising, because a malformed claim is a refusal, not a crash.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    expanded = os.path.expanduser(text)
    try:
        return str(Path(expanded).resolve())
    except (OSError, RuntimeError):
        return str(Path(os.path.abspath(expanded)))


def read_claims(lanes: Mapping[str, Any]) -> List[LaneClaim]:
    """Project the state document's lanes into claims.

    A lane with neither a worktree nor a branch cannot collide with anything,
    so it is skipped rather than registered as an empty claim.
    """
    claims: List[LaneClaim] = []
    for lane_id, lane in (lanes or {}).items():
        if not isinstance(lane, Mapping):
            continue
        worktree = str(lane.get("worktree") or lane.get("cwd") or "")
        branch = str(lane.get("branch") or "")
        if not worktree and not branch:
            continue
        claims.append(
            LaneClaim(
                lane_id=str(lane_id),
                worktree=worktree,
                branch=branch,
                status=str(lane.get("status") or ""),
            )
        )
    return claims


def _holder_for(
    claims: Iterable[LaneClaim],
    *,
    lane_id: str,
    matcher,
    resource: str,
    requested: str,
) -> Optional[LaneClaim]:
    """Find a live claim other than ``lane_id`` that matches ``matcher``."""
    for claim in claims:
        if claim.lane_id == lane_id or claim.released:
            continue
        if matcher(claim):
            return claim
    return None


def audit_claim(
    lanes: Mapping[str, Any],
    lane_id: str,
    *,
    worktree: str = "",
    branch: str = "",
) -> ClaimAudit:
    """Check whether ``lane_id`` may claim ``worktree`` and ``branch``.

    Pure and side-effect free, so the caller decides whether a refusal aborts a
    dispatch or merely annotates it.
    """
    claims = read_claims(lanes)
    resolved_worktree = normalise_path(worktree)
    resolved_branch = (branch or "").strip()
    violations: List[str] = []

    if not resolved_worktree and not resolved_branch:
        violations.append(
            "a lane must claim at least a worktree or a branch; "
            "an unclaimed lane cannot be isolated from its peers"
        )

    worktree_holder = None
    if resolved_worktree:
        worktree_holder = _holder_for(
            claims,
            lane_id=lane_id,
            matcher=lambda c: bool(c.worktree)
            and normalise_path(c.worktree) == resolved_worktree,
            resource="worktree",
            requested=resolved_worktree,
        )
        if worktree_holder is not None:
            violations.append(
                f"worktree {resolved_worktree} is already claimed by live lane "
                f"{worktree_holder.lane_id!r}; 1 Lane = 1 Worktree = 1 Branch "
                "forbids sharing a worktree between interactive agents"
            )

    branch_holder = None
    if resolved_branch:
        branch_holder = _holder_for(
            claims,
            lane_id=lane_id,
            matcher=lambda c: bool(c.branch) and c.branch == resolved_branch,
            resource="branch",
            requested=resolved_branch,
        )
        if branch_holder is not None:
            violations.append(
                f"branch {resolved_branch!r} is already claimed by live lane "
                f"{branch_holder.lane_id!r}; two lanes on one branch interleave "
                "commits and each would merge the other's untested work"
            )

    return ClaimAudit(
        lane_id=lane_id,
        ok=not violations,
        worktree=resolved_worktree,
        branch=resolved_branch,
        existing=claims,
        violations=violations,
    )


def claim_lane(
    lanes: Mapping[str, Any],
    lane_id: str,
    *,
    worktree: str = "",
    branch: str = "",
) -> ClaimAudit:
    """Claim a worktree and branch for a lane, or raise.

    The dispatch-time gate: :func:`audit_claim` plus the refusal. Callers that
    want a report instead of an exception use :func:`audit_claim` directly.
    """
    audit = audit_claim(lanes, lane_id, worktree=worktree, branch=branch)
    if audit.ok:
        return audit

    holder = ""
    for claim in audit.existing:
        if claim.lane_id != lane_id and not claim.released:
            if (
                claim.worktree
                and normalise_path(claim.worktree) == audit.worktree
            ) or (claim.branch and claim.branch == audit.branch):
                holder = claim.lane_id
                break

    raise LaneCollisionError(
        f"lane {lane_id!r} refused: "
        + "; ".join(audit.violations)
        + ". Give each lane its own worktree and branch, or close out the "
        "holding lane first.",
        lane_id=lane_id,
        resource="worktree" if any("worktree" in v for v in audit.violations) else "branch",
        holder=holder,
        requested=audit.worktree or audit.branch,
    )