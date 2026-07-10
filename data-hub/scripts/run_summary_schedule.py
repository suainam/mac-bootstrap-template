#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent
TEMPLATE_ROOT = DATA_HUB_DIR.parent
MANAGER = (
    TEMPLATE_ROOT
    / "agent-skills"
    / "local"
    / "global"
    / "knowledge-lifecycle-manager"
    / "scripts"
    / "manager.py"
)
PYTHON = TEMPLATE_ROOT / ".venv" / "bin" / "python"

if str(DATA_HUB_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_HUB_DIR))

import summary_calendar
from data_hub_config import get_runtime_config
from db_helper import get_db_connection
from period_summary import resolve_period_coverage


PREVIOUS_LEVEL = {
    "weekly": "daily",
    "monthly": "weekly",
    "quarterly": "monthly",
    "yearly": "quarterly",
}
_AUTO_CONNECTION = object()


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _current_lower_period_covered(
    conn: sqlite3.Connection,
    *,
    higher_level: str,
    anchor_date: str,
    deployment_start: str,
) -> bool:
    lower_level = PREVIOUS_LEVEL[higher_level]
    higher = resolve_period_coverage(higher_level, anchor_date)
    lower = resolve_period_coverage(lower_level, anchor_date)
    required_start = max(higher.period_start, lower.period_start, deployment_start)
    required_end = min(higher.coverage_end, lower.period_end)
    if required_start > required_end:
        return True
    row = conn.execute(
        """
        SELECT 1
        FROM summaries s
        JOIN summary_revisions r ON r.revision_id = s.current_revision_id
        WHERE s.summary_level = ?
          AND s.period_id = ?
          AND r.publish_status = 'published'
          AND r.coverage_start <= ?
          AND r.coverage_end >= ?
        LIMIT 1
        """,
        (lower_level, lower.period_id, required_start, required_end),
    ).fetchone()
    return row is not None


def planned_workflows(
    anchor_date: str,
    *,
    conn: sqlite3.Connection | None | object = _AUTO_CONNECTION,
    deployment_start: str | None = None,
) -> list[str]:
    levels = ["daily", "weekly", "monthly", "quarterly", "yearly"]
    triggered = {level for level in levels if summary_calendar.is_summary_trigger_day(level, anchor_date)}
    owns_connection = conn is _AUTO_CONNECTION
    active_conn = get_db_connection() if owns_connection else conn
    deployment_start = deployment_start or get_runtime_config().summary.deployment_start
    closure = set(triggered)
    try:
        for level in ("yearly", "quarterly", "monthly", "weekly"):
            if level not in closure:
                continue
            lower = PREVIOUS_LEVEL[level]
            covered = False
            if active_conn is not None:
                covered = _current_lower_period_covered(
                    active_conn,
                    higher_level=level,
                    anchor_date=anchor_date,
                    deployment_start=deployment_start,
                )
            if not covered and (lower != "daily" or summary_calendar.is_summary_trigger_day("daily", anchor_date)):
                closure.add(lower)
        return [f"build_{level}_summary" for level in levels if level in closure]
    finally:
        if owns_connection and isinstance(active_conn, sqlite3.Connection):
            active_conn.close()


def run_workflow(workflow: str, anchor_date: str) -> None:
    subprocess.run(
        [str(PYTHON), str(MANAGER), "run", "--workflow", workflow, "--date", anchor_date],
        check=True,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run scheduled data-hub summary workflows.")
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    workflows = planned_workflows(args.date)
    print("\n".join(workflows))
    if args.dry_run:
        return
    for workflow in workflows:
        run_workflow(workflow, args.date)


if __name__ == "__main__":
    main()
