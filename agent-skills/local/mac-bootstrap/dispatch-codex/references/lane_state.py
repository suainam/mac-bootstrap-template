#!/usr/bin/env python3
"""
lane_state.py — Codex lane probe helper for dispatch-codex (#111)

Usage:
    python3 lane_state.py <session-uuid>

Output: JSON object with fields defined by driver.md §6a probe contract:
    turn_state    "working" | "complete" | "unknown"
    used_pct      float | null
    compactions   int
    mtime         ISO-8601 string of rollout file last-modified
    out_of_room   bool
    goal_status   "active"|"paused"|"blocked"|"usage_limited"|"budget_limited"|"complete"|null
    goal_tokens   int | null
    probe         "ok" | "unavailable:<reason>"

Written by the orchestrator at runtime to ~/.omp/dispatch-codex/bin/lane_state.py
if absent (driver.md §6a).
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


TAIL_BYTES = 2 * 1024 * 1024  # 2 MB — rollout files can reach 100+ MB


def find_rollout(uuid: str) -> Optional[Path]:
    """Find rollout file by uuid suffix under ~/.codex/sessions/."""
    sessions = Path.home() / ".codex" / "sessions"
    if not sessions.exists():
        return None
    # Search today first, then all dates — O(dates) not O(all files)
    today = datetime.now().strftime("%Y/%m/%d")
    search_dirs = [sessions / today] + sorted(
        (d for d in sessions.glob("*/*/*") if d.is_dir() and str(d) != str(sessions / today)),
        reverse=True,
    )
    for d in search_dirs:
        candidate = next(d.glob(f"rollout-*-{uuid}.jsonl"), None)
        if candidate:
            return candidate
    return None


def read_tail(path: Path) -> bytes:
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > TAIL_BYTES:
            f.seek(size - TAIL_BYTES)
            _ = f.readline()  # skip partial line
        return f.read()


def parse_rollout(tail: bytes) -> dict:
    """Extract turn_state, used_pct, compactions, out_of_room from rollout tail."""
    turn_events = {"task_started", "task_complete", "turn_aborted"}
    last_turn_event = None
    last_token_usage = None
    model_context_window = None
    compactions = 0
    out_of_room = False

    for raw in tail.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue

        t = rec.get("type", "")

        if t == "compacted":
            compactions += 1

        if t in turn_events:
            last_turn_event = t

        if t == "token_count":
            u = rec.get("last_token_usage") or rec.get("usage")
            if u:
                last_token_usage = u
            cw = rec.get("model_context_window")
            if cw:
                model_context_window = cw

        # Codex "ran out of room" marker
        msg = str(rec.get("message", "")) + str(rec.get("content", ""))
        if "ran out of room" in msg.lower():
            out_of_room = True

    turn_state = "unknown"
    if last_turn_event == "task_complete":
        turn_state = "complete"
    elif last_turn_event in ("task_started", "turn_aborted"):
        turn_state = "working"

    used_pct = None
    if last_token_usage and model_context_window:
        inp = last_token_usage.get("input_tokens", 0)
        used_pct = round(inp / model_context_window * 100, 1)

    return {
        "turn_state": turn_state,
        "used_pct": used_pct,
        "compactions": compactions,
        "out_of_room": out_of_room,
    }


def query_goal(uuid: str) -> dict:
    """Query ~/.codex/goals_1.sqlite for this lane's goal status and tokens."""
    db = Path.home() / ".codex" / "goals_1.sqlite"
    if not db.exists():
        return {"goal_status": None, "goal_tokens": None}
    try:
        conn = sqlite3.connect(str(db), timeout=5)
        row = conn.execute(
            "SELECT status, tokens_used FROM thread_goals WHERE thread_id = ? ORDER BY rowid DESC LIMIT 1",
            (uuid,),
        ).fetchone()
        conn.close()
        if row:
            return {"goal_status": row[0], "goal_tokens": row[1]}
    except sqlite3.Error:
        pass
    return {"goal_status": None, "goal_tokens": None}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"probe": "unavailable:missing session-uuid argument"}))
        sys.exit(1)

    uuid = sys.argv[1].strip()
    rollout = find_rollout(uuid)

    if rollout is None:
        print(json.dumps({
            "turn_state": "unknown",
            "used_pct": None,
            "compactions": 0,
            "mtime": None,
            "out_of_room": False,
            "goal_status": None,
            "goal_tokens": None,
            "probe": f"unavailable:rollout not found for uuid={uuid}",
        }))
        sys.exit(0)

    tail = read_tail(rollout)
    parsed = parse_rollout(tail)
    goal = query_goal(uuid)

    mtime = datetime.fromtimestamp(
        rollout.stat().st_mtime, tz=timezone.utc
    ).isoformat()

    result = {
        "turn_state": parsed["turn_state"],
        "used_pct": parsed["used_pct"],
        "compactions": parsed["compactions"],
        "mtime": mtime,
        "out_of_room": parsed["out_of_room"],
        "goal_status": goal["goal_status"],
        "goal_tokens": goal["goal_tokens"],
        "probe": "ok",
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
