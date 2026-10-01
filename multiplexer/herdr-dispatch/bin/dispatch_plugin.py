"""Plugin entrypoint — TB-03.

Every command Herdr launches is a fresh, short-lived process, so this module
does no caching between invocations and owns no long-running state. It reads
the shared state file, projects lanes into the sidebar, and exits.

Decoupling
----------
The plugin is one of two deliberately orthogonal surfaces.

- **This side (Herdr)** is one-shot argv commands. It knows panes, worktrees,
  tokens and the board. It has no idea the omp extension exists.
- **The other side (omp)** is in-process. It owns the brain loop, routing and
  the human gate. It never touches the Herdr CLI.

They communicate through exactly one thing: the state file. Nothing here
imports anything omp-side, which is what keeps the plugin reusable in any
project.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import closeout_gate as gate  # noqa: E402
import herdr_client as herdr  # noqa: E402
import lane_isolation as isolation  # noqa: E402
import orchestrator_state as brain  # noqa: E402

PLUGIN_SOURCE = "plugin:herdr-dispatch"

# Gate refusals are a distinct exit code from a generic failure: 2 means "the
# lifecycle rules refused this", which an orchestrator must not retry past.
EXIT_GATE_REFUSED = 2


def state_path(args: argparse.Namespace) -> Path:
    return brain.state_path(Path(args.repo) if args.repo else None)


def _state(repo: Optional[str]) -> Dict[str, Any]:
    path = brain.state_path(Path(repo) if repo else None)
    try:
        return brain.load(path)
    except brain.StateError as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return brain.default_state()


def _lanes(state: Mapping[str, Any]) -> List[Dict[str, Any]]:
    lanes = state.get("lanes") or {}
    out: List[Dict[str, Any]] = []
    for lane_id, lane in sorted(lanes.items()):
        if isinstance(lane, Mapping):
            entry = dict(lane)
            entry.setdefault("lane", lane_id)
            out.append(entry)
    return out


# --------------------------------------------------------------------------
# startup
# --------------------------------------------------------------------------


def cmd_startup(args: argparse.Namespace) -> int:
    """Reconcile the pane registry after a session restore.

    Runs once per enabled plugin after Herdr restores the session and its API
    socket is ready. It is not a daemon: a failure here must not stop the
    server, so every error path reports and returns rather than raising.
    """
    state = _state(args.repo)
    phase = state.get("orchestrator_phase", "unknown")

    # Retire lanes whose pane no longer exists, keeping the evidence. Silently
    # dropping them would make a crashed worker look like a finished one.
    live: Dict[str, Any] = {}
    if herdr.in_herdr():
        try:
            live = {
                a.get("pane_id"): a
                for a in herdr.agent_list()
                if a.get("pane_id")
            }
        except herdr.HerdrError as exc:
            print(f"dispatch startup: agent list unavailable ({exc})")

    lanes = _lanes(state)
    orphans: List[str] = []
    for lane in lanes:
        pane_id = lane.get("pane_id") or lane.get("pane")
        if not pane_id:
            continue
        if pane_id in live:
            # Read-only: Herdr's integration owns this value.
            lane["status"] = live[pane_id].get("agent_status", lane.get("status"))
        else:
            lane["status"] = "orphaned"
            lane["orphan_pane"] = pane_id
            orphans.append(lane["lane"])

    if lanes:
        try:
            brain.update(state_path(args), {"lanes": {l["lane"]: l for l in lanes}})
        except brain.StateError as exc:
            print(f"dispatch startup: state update skipped ({exc})")

    # The view projection is opt-in and off by default; installing it unasked
    # would replace the session's agent_panel_sort policy.
    if herdr.view_enabled_by_default():
        try:
            herdr.set_agent_view(plugin_id=herdr.plugin_root().name, enabled=True)
        except herdr.HerdrError as exc:
            print(f"dispatch startup: agent view not applied ({exc})")

    print(
        f"dispatch startup: phase={phase} lanes={len(lanes)} orphaned={len(orphans)}"
    )
    return 0


# --------------------------------------------------------------------------
# project
# --------------------------------------------------------------------------


def cmd_project(args: argparse.Namespace) -> int:
    """Publish each lane's presentation tokens into the Herdr sidebar.

    Token publication only. Lifecycle status keeps coming from the integration
    that owns it, which is why this reads ``agent_status`` and never writes a
    lifecycle value.
    """
    state = _state(args.repo)
    phase = state.get("orchestrator_phase", "")

    published = 0
    for lane in _lanes(state):
        pane_id = lane.get("pane_id") or lane.get("pane")
        if not pane_id:
            continue
        try:
            herdr.report_lane_metadata(pane_id, lane, brain_phase=phase)
            published += 1
        except herdr.HerdrError as exc:
            print(f"dispatch: pane {pane_id} not projected ({exc})", file=sys.stderr)

    print(f"dispatch: projected {published} lane(s)")
    return 0


# --------------------------------------------------------------------------
# status / harvest / view
# --------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    state = _state(args.repo)
    if args.json:
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0
    print(f"brain: {state.get('orchestrator_phase')}")
    if state.get("blocked_reason"):
        print(f"  {state['blocked_reason']}")
    for lane in _lanes(state):
        pane = lane.get("pane_id") or lane.get("pane") or "-"
        print(
            f"  {lane['lane']:<22} {lane.get('status', '?'):<10} "
            f"pane={pane} handoff={'yes' if lane.get('handoff') else 'no'}"
        )
    return 0


def cmd_harvest(args: argparse.Namespace) -> int:
    """Collect lane handoffs and surface any lane still waiting on one.

    Publication stays with the human: this reports, it never pushes.
    """
    state = _state(args.repo)
    ready: List[str] = []
    waiting: List[str] = []
    for lane in _lanes(state):
        handoff = lane.get("handoff")
        if handoff and Path(os.path.expanduser(str(handoff))).is_file():
            ready.append(f"{lane['lane']}: {handoff}")
        else:
            waiting.append(lane["lane"])

    for entry in ready:
        print(f"ready  {entry}")
    for entry in waiting:
        print(f"wait   {entry}")

    if args.notify and ready:
        herdr.notify(
            f"dispatch: {len(ready)} lane(s) ready",
            "; ".join(r.split(":")[0] for r in ready)[:200],
        )
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    if args.off:
        print(json.dumps(herdr.set_agent_view(plugin_id=herdr.plugin_root().name, enabled=False)))
        return 0
    if not args.on:
        print(
            "pass --on or --off; the projection replaces the session's "
            "agent_panel_sort policy, so it is opt-in"
        )
        return 0
    print(json.dumps(herdr.set_agent_view(plugin_id=herdr.plugin_root().name, enabled=True)))
    return 0


# --------------------------------------------------------------------------
# isolation / closeout gates
# --------------------------------------------------------------------------


def cmd_claim(args: argparse.Namespace) -> int:
    """Claim a worktree and branch for a lane, or refuse.

    The dispatch-time anti-stomping check. ``--worktree``/``--branch`` describe
    the lane about to be dispatched; the refusal is the product, so a collision
    exits 2 rather than degrading to a warning.
    """
    state = _state(args.repo)
    lanes = state.get("lanes") or {}

    audit = isolation.audit_claim(
        lanes,
        args.lane,
        worktree=args.worktree or "",
        branch=args.branch or "",
    )
    if args.json:
        print(json.dumps(audit.as_dict(), indent=2, ensure_ascii=False))
        return 0 if audit.ok else EXIT_GATE_REFUSED

    if not audit.ok:
        for violation in audit.violations:
            print(f"dispatch: lane {args.lane}: {violation}", file=sys.stderr)
        return EXIT_GATE_REFUSED

    print(f"dispatch: lane {args.lane} may claim {audit.worktree} @ {audit.branch}")
    return 0


def cmd_closeout(args: argparse.Namespace) -> int:
    """Evaluate the Closeout Lifecycle Gate for one lane.

    Reports whether the worktree may be destroyed and whether the worker pane
    may be closed. It never closes anything itself: the gate that authorises an
    irreversible action cannot also be the thing that performs it.
    """
    evidence: Dict[str, Dict[str, Any]] = {}
    if args.evidence:
        try:
            loaded = json.loads(args.evidence)
        except json.JSONDecodeError as exc:
            print(f"dispatch: --evidence is not valid JSON ({exc})", file=sys.stderr)
            return 2
        if not isinstance(loaded, dict):
            print("dispatch: --evidence must be a JSON object", file=sys.stderr)
            return 2
        evidence = {k: v for k, v in loaded.items() if isinstance(v, dict)}

    report = gate.evaluate_closeout(args.lane, evidence)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.render())
    return 0 if report.allowed else EXIT_GATE_REFUSED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dispatch-plugin", description="herdr-dispatch plugin commands (TB-03)"
    )
    parser.add_argument("--repo", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    startup = sub.add_parser("startup", help="reconcile panes after session restore")
    startup.set_defaults(func=cmd_startup)

    project = sub.add_parser("project", help="publish lane tokens to the sidebar")
    project.set_defaults(func=cmd_project)

    status = sub.add_parser("status", help="show brain phase and lanes")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    harvest = sub.add_parser("harvest", help="collect lane handoffs")
    harvest.add_argument("--notify", action="store_true")
    harvest.set_defaults(func=cmd_harvest)

    view = sub.add_parser("view", help="install or clear the Agents view projection")
    view.add_argument("--on", action="store_true")
    view.add_argument("--off", action="store_true")
    view.set_defaults(func=cmd_view)

    claim = sub.add_parser(
        "claim", help="claim a worktree and branch for a lane (1 Lane = 1 Worktree = 1 Branch)"
    )
    claim.add_argument("--lane", required=True)
    claim.add_argument("--worktree", default="")
    claim.add_argument("--branch", default="")
    claim.add_argument("--json", action="store_true")
    claim.set_defaults(func=cmd_claim)

    closeout = sub.add_parser(
        "closeout", help="evaluate the Closeout Lifecycle Gate before cleanup/pane close"
    )
    closeout.add_argument("--lane", default="")
    closeout.add_argument(
        "--evidence", default="", help="JSON object of closeout step facts"
    )
    closeout.add_argument("--json", action="store_true")
    closeout.set_defaults(func=cmd_closeout)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (
        brain.StateError,
        herdr.HerdrError,
        isolation.LaneCollisionError,
        gate.CloseoutGateError,
    ) as exc:
        # A plugin command must fail visibly but never wedge the server. Gate
        # refusals land here too, and deliberately share exit 2: an orchestrator
        # must not be able to tell "the lifecycle rules refused this" apart from
        # "something broke" and sail past it.
        print(f"dispatch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())