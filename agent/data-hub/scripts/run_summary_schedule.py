#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent
TEMPLATE_ROOT = DATA_HUB_DIR.parents[1]
MANAGER = TEMPLATE_ROOT / "agent" / "skills" / "personal" / "knowledge-lifecycle-manager" / "scripts" / "manager.py"
PYTHON = TEMPLATE_ROOT / ".venv" / "bin" / "python"

if str(DATA_HUB_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_HUB_DIR))

import summary_calendar


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def planned_workflows(anchor_date: str) -> list[str]:
    workflows = []
    for level in ["daily", "weekly", "monthly", "quarterly", "yearly"]:
        if summary_calendar.is_summary_trigger_day(level, anchor_date):
            workflows.append(f"build_{level}_summary")
    return workflows


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
