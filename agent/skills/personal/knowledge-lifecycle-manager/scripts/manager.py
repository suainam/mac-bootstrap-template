#!/usr/bin/env python3
"""Knowledge Lifecycle Manager - Unified data-hub pipeline control."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[6]
TEMPLATE_ROOT = REPO_ROOT / "template"
DATA_HUB = TEMPLATE_ROOT / "agent" / "data-hub"
PYTHON = TEMPLATE_ROOT / ".venv" / "bin" / "python"
DB_PATH = REPO_ROOT / "private" / "agent" / "data" / "agent_history.db"

sys.path.insert(0, str(DATA_HUB))
from db_helper import get_db_connection
import knowledge_workflows


def default_target_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_env() -> None:
    """Load private environment."""
    env_path = REPO_ROOT / "private" / "agent" / ".obsidian_daily.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")


def run_workflow(workflow_name: str, target_date: str) -> None:
    """Run a named workflow for target_date."""
    print(f"\nStarting workflow={workflow_name} for {target_date}\n")

    steps = knowledge_workflows.build_workflow_steps(workflow_name, target_date)
    for index, step in enumerate(steps, start=1):
        print(f"[{index}/{len(steps)}] {step['name']}")
        result = subprocess.run(
            step["command"],
            cwd=DATA_HUB,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            if result.stdout.strip():
                print(result.stdout.strip())
            print(result.stderr.strip() or f"{step['name']} failed")
            sys.exit(1)

        if result.stdout.strip():
            print(result.stdout.strip())

    print(f"\nWorkflow {workflow_name} completed for {target_date}\n")


def show_status(target_date: str) -> None:
    """Show execution status for target_date."""
    load_env()
    conn = get_db_connection()
    cursor = conn.execute(
        """
        SELECT step_name, started_at, completed_at, status, records_affected, error_message
        FROM execution_log
        WHERE execution_date = ?
        ORDER BY started_at ASC
        """,
        (target_date,),
    )

    rows = cursor.fetchall()
    if not rows:
        print(f"No execution logs found for {target_date}")
        return

    print(f"\nExecution Status for {target_date}\n")
    print(f"{'Step':<25} {'Status':<10} {'Records':<10} {'Duration':<12} {'Error'}")
    print("-" * 90)

    for row in rows:
        step, started, completed, status, records, error = row
        duration = ""
        if started and completed:
            start_dt = datetime.fromisoformat(started)
            end_dt = datetime.fromisoformat(completed)
            duration = f"{(end_dt - start_dt).total_seconds():.1f}s"

        status_icon = {"completed": "OK", "failed": "FAIL", "running": "RUN"}.get(status, "UNK")
        error_msg = error[:40] if error else ""

        print(f"{step:<25} {status_icon} {status:<8} {records:<10} {duration:<12} {error_msg}")

    conn.close()
    print()


def show_candidates(target_date: str) -> None:
    """Show candidate queue statistics for target_date."""
    load_env()
    conn = get_db_connection()

    cursor = conn.execute(
        """
        SELECT status, candidate_type, COUNT(*) as count
        FROM knowledge_candidates
        WHERE candidate_date = ?
        GROUP BY status, candidate_type
        ORDER BY status, candidate_type
        """,
        (target_date,),
    )

    rows = cursor.fetchall()
    if not rows:
        print(f"No candidates found for {target_date}")
        conn.close()
        return

    print(f"\nCandidate Queue for {target_date}\n")
    print(f"{'Status':<12} {'Type':<15} {'Count'}")
    print("-" * 40)

    total_by_status: dict[str, int] = {}
    for status, cand_type, count in rows:
        print(f"{status:<12} {cand_type:<15} {count}")
        total_by_status[status] = total_by_status.get(status, 0) + count

    print("-" * 40)
    for status, total in sorted(total_by_status.items()):
        print(f"{'Total':<12} {status:<15} {total}")

    conn.close()
    print()


def health_check() -> None:
    """Check last 3 days for failed steps."""
    load_env()
    conn = get_db_connection()

    today = datetime.now().date()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]

    cursor = conn.execute(
        """
        SELECT execution_date, step_name, status, error_message
        FROM execution_log
        WHERE execution_date IN (?, ?, ?) AND status = 'failed'
        ORDER BY execution_date DESC, started_at DESC
        """,
        tuple(dates),
    )

    rows = cursor.fetchall()
    if not rows:
        print("\nHealth Check: All clear (last 3 days)\n")
        conn.close()
        return

    print(f"\nHealth Check: {len(rows)} failed steps in last 3 days\n")
    print(f"{'Date':<12} {'Step':<25} {'Error'}")
    print("-" * 80)

    for date, step, _status, error in rows:
        error_msg = error[:50] if error else "Unknown error"
        print(f"{date:<12} {step:<25} {error_msg}")

    conn.close()
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Knowledge Lifecycle Manager - Unified data-hub pipeline control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s run --workflow full_cycle --date 2026-07-01
  %(prog)s status --date 2026-07-01
  %(prog)s candidates 2026-07-01
  %(prog)s health

Legacy aliases:
  %(prog)s --ingest-only
  %(prog)s --review-only
  %(prog)s --materialize-only
  %(prog)s --status
  %(prog)s --candidates
  %(prog)s --health
        """,
    )
    parser.add_argument("command", nargs="?", choices=["run", "status", "candidates", "health"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--run", action="store_true", help="Run a workflow (default)")
    parser.add_argument("--workflow", choices=knowledge_workflows.supported_workflows(), default="full_cycle")
    parser.add_argument("--date", type=str, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--ingest-only", action="store_true", help="Legacy alias for daily_ingest_and_review")
    parser.add_argument("--review-only", action="store_true", help="Legacy alias for auto_review_only")
    parser.add_argument("--materialize-only", action="store_true", help="Legacy alias for materialize_only")
    parser.add_argument("--status", action="store_true", help="Show execution status")
    parser.add_argument("--candidates", nargs="?", const="TODAY", help="Show candidate queue")
    parser.add_argument("--health", action="store_true", help="Health check (last 3 days)")
    return parser


def resolve_action(args: argparse.Namespace) -> tuple[str, str | None, str | None]:
    target_date = args.date or default_target_date()

    if args.health or args.command == "health":
        return ("health", None, None)
    if args.status or args.command == "status":
        status_date = args.date or args.value or default_target_date()
        return ("status", None, status_date)
    if args.candidates is not None or args.command == "candidates":
        if args.candidates is not None:
            candidate_date = default_target_date() if args.candidates == "TODAY" else args.candidates
        else:
            candidate_date = args.date or args.value or default_target_date()
        return ("candidates", None, candidate_date)
    if args.ingest_only:
        return ("run", "daily_ingest_and_review", target_date)
    if args.review_only:
        return ("run", "auto_review_only", target_date)
    if args.materialize_only:
        return ("run", "materialize_only", target_date)
    if args.command == "run" or args.run:
        return ("run", args.workflow, target_date)
    return ("run", args.workflow, target_date)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    action, workflow_name, target_date = resolve_action(args)

    if action == "health":
        health_check()
        return
    if action == "status":
        show_status(target_date or default_target_date())
        return
    if action == "candidates":
        show_candidates(target_date or default_target_date())
        return

    run_workflow(workflow_name or "full_cycle", target_date or default_target_date())


if __name__ == "__main__":
    main()
