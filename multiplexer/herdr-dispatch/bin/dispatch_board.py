"""Lane board — TB-03.

A terminal view of the dispatch run, rendered as a plain TUI in a Herdr popup
pane.

Deliberately plain
------------------
Upstream `bestony/herdr-dispatch` ships no TUI at all: its observability is a
disk probe plus a text report. So this does not introduce a widget toolkit, a
table engine or a render loop. It reads the shared state file, asks Herdr for
one read per lane, and prints. Kitty graphics are used only for a small status
glyph, with a plain-text fallback.
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

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
GREEN = "\x1b[32m"
CYAN = "\x1b[36m"

# Kitty graphics placeholders (a 1x1 solid cell per colour). Kept tiny so the
# popup stays a text-first view.
KITTY_ON = os.environ.get("HERDR_DISPATCH_KITTY", "1") not in ("0", "false", "no")


def use_colour() -> bool:
    """Honour the usual opt-outs; a popup must stay readable when piped."""
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def paint(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if use_colour() else text


def status_style(status: str) -> str:
    return {
        "blocked": RED,
        "done": GREEN,
        "working": CYAN,
        "idle": YELLOW,
    }.get(status, DIM)


def glyph(status: str) -> str:
    return {"blocked": "!", "done": "+", "working": "~", "idle": "."}.get(status, "?")


def load_state(repo: Optional[str]) -> Dict[str, Any]:
    path = brain.state_path(Path(repo) if repo else None)
    try:
        return brain.load(path)
    except brain.StateError as exc:
        print(paint(f"dispatch: unreadable state ({exc})", RED), file=sys.stderr)
        return brain.default_state()


def collect_rows(state: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """One row per lane that still has a pane.

    Lane identity comes from the state file; Herdr supplies the live status.
    Lanes whose pane is gone are reported separately rather than hidden.
    """
    lanes = state.get("lanes") or {}
    rows: List[Dict[str, Any]] = []
    for lane_id, lane in sorted(lanes.items()):
        if not isinstance(lane, Mapping):
            continue
        pane_id = lane.get("pane_id") or lane.get("pane") or ""
        info: Dict[str, Any] = {}
        queried = bool(pane_id) and herdr.in_herdr()
        if queried:
            try:
                info = herdr.agent_info(pane_id)
            except herdr.HerdrError:
                info = {}
        rows.append(
            {
                "lane": lane_id,
                "wave": str(lane.get("wave", "")),
                "role": lane.get("role", ""),
                "kind": lane.get("kind", ""),
                "pane": pane_id,
                # Read-only: Herdr's integration owns this value.
                "status": info.get("agent_status") or lane.get("status") or "unknown",
                "state_change_seq": info.get("state_change_seq"),
                "handoff": lane.get("handoff"),
                # None when Herdr was not consulted, so the board does not
                # claim a pane is gone just because it could not ask.
                "alive": bool(info) if queried else None,
            }
        )
    return rows


def render(state: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    lines: List[str] = []
    phase = state.get("orchestrator_phase") or "unknown"
    parked = phase == "yield_and_guard"

    title = "dispatch lanes"
    lines.append(paint(title, BOLD))
    brain_line = f"brain: {phase}"
    if parked:
        brain_line += paint("  (parked — awaiting worker IPC)", DIM)
    lines.append(brain_line)
    if state.get("blocked_reason"):
        lines.append(paint(f"  {state['blocked_reason']}", DIM))
    waiting = (state.get("brain") or {}).get("awaiting_lanes") or []
    if waiting:
        lines.append(paint(f"  waiting on: {', '.join(waiting)}", DIM))
    lines.append("")

    if not rows:
        lines.append(paint("no lanes recorded", DIM))
        return "\n".join(lines)

    header = f"  {'LANE':<22} {'WAVE':<5} {'ROLE':<11} {'KIND':<10} {'PANE':<9} STATUS"
    lines.append(paint(header, DIM))
    for row in rows:
        status = str(row["status"])
        style = status_style(status)
        mark = glyph(status)
        lane_cell = f"{mark} {row['lane']}"[:22].ljust(22)
        line = (
            "  "
            + lane_cell
            + f" {str(row['wave'] or '-'):<5}"
            + f" {str(row['role'] or '-'):<11}"
            + f" {str(row['kind'] or '-'):<10}"
            + f" {str(row['pane'] or '-'):<9}"
            + paint(status, style)
        )
        if row["alive"] is False:
            line += paint("  (pane gone)", RED)
        elif not row["handoff"]:
            line += paint("  (no handoff yet)", DIM)
        lines.append(line)

    blocked = [r for r in rows if r["status"] == "blocked"]
    if blocked:
        lines.append("")
        lines.append(
            paint(f"  {len(blocked)} lane(s) blocked — press enter on the pane to inspect", YELLOW)
        )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dispatch-board", description="Render dispatch lanes (TB-03)"
    )
    parser.add_argument("--repo", default=None)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--once", action="store_true", help="render once and exit")
    args = parser.parse_args(argv)

    state = load_state(args.repo)
    rows = collect_rows(state)

    if args.json:
        print(json.dumps({"brain": state.get("orchestrator_phase"), "rows": rows}, indent=2))
        return 0

    print(render(state, rows))
    if args.once:
        return 0

    # Stay open as a popup, but never busy-wait: a slow poll keeps the pane
    # cheap and gives the operator a live view without a render loop.
    try:
        while True:
            try:
                import time

                time.sleep(5)
            except KeyboardInterrupt:
                return 0
            state = load_state(args.repo)
            rows = collect_rows(state)
            sys.stdout.write("\x1b[H\x1b[2J")
            sys.stdout.write(render(state, rows) + "\n")
            sys.stdout.flush()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())