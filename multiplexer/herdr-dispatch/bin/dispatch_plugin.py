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

import herdr_client as herdr  # noqa: E402
import orchestrator_state as brain  # noqa: E402

PLUGIN_SOURCE = "plugin:herdr-dispatch"


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

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (brain.StateError, herdr.HerdrError) as exc:
        # A plugin command must fail visibly but never wedge the server.
        print(f"dispatch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())