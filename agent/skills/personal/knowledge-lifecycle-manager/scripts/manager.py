#!/usr/bin/env python3
"""Knowledge Lifecycle Manager - Unified data-hub pipeline control."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[6]
TEMPLATE_ROOT = REPO_ROOT / "template"
DATA_HUB = TEMPLATE_ROOT / "agent" / "data-hub"
PYTHON = TEMPLATE_ROOT / ".venv" / "bin" / "python"
DB_PATH = REPO_ROOT / "private" / "agent" / "data" / "agent_history.db"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(DATA_HUB))
from db_helper import get_db_connection
import knowledge_workflows
import manager_reporting


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


def _db_path_from_env() -> Path:
    return Path(os.path.expandvars(os.environ.get("AGENT_DB_PATH", str(DB_PATH))))


def run_workflow(
    workflow_name: str,
    target_date: str,
    *,
    run_id: str | None = None,
    resume_run_id: str | None = None,
    retry_failed_run_id: str | None = None,
    from_step: str | None = None,
    max_attempts: int = 1,
) -> None:
    """Run a named workflow for target_date."""
    print(f"\nStarting workflow={workflow_name} for {target_date}\n")

    results = knowledge_workflows.run_workflow(
        workflow_name,
        target_date,
        durable=True,
        run_id=run_id,
        resume_run_id=resume_run_id,
        retry_failed_run_id=retry_failed_run_id,
        from_step=from_step,
        max_attempts=max_attempts,
    )

    active_run_id = results[0]["run_id"] if results else run_id or resume_run_id or retry_failed_run_id
    if active_run_id:
        print(f"Run ID: {active_run_id}")

    failed = None
    for index, result in enumerate(results, start=1):
        print(f"[{index}/{len(results)}] {result['name']}: {result['status']}")
        if result.get("stdout_path"):
            print(f"  stdout: {result['stdout_path']}")
        if result.get("stderr_path"):
            print(f"  stderr: {result['stderr_path']}")
        if result["status"] == "failed":
            failed = result
            break

    if failed:
        print(f"\nWorkflow {workflow_name} failed at {failed['name']}")
        if active_run_id:
            print(f"Resume: {Path(__file__)} run --workflow {workflow_name} --date {target_date} --retry-failed {active_run_id}")
        sys.exit(1)

    print(f"\nWorkflow {workflow_name} completed for {target_date}\n")


def show_status(target_date: str) -> None:
    """Show execution status for target_date."""
    manager_reporting.show_status(target_date, load_env=load_env, get_db_connection=get_db_connection)


def show_candidates(target_date: str) -> None:
    """Show candidate queue statistics for target_date."""
    manager_reporting.show_candidates(target_date, load_env=load_env, get_db_connection=get_db_connection)


def health_check() -> None:
    """Check last 3 days for failed steps."""
    manager_reporting.health_check(load_env=load_env, get_db_connection=get_db_connection)


def backup_database(target_date: str) -> None:
    """Create a verified SQLite backup and record it in backup_log."""
    manager_reporting.backup_database(
        target_date,
        db_path=_db_path_from_env(),
        load_env=load_env,
        get_db_connection=get_db_connection,
    )


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
  %(prog)s backup --date 2026-07-01

Legacy aliases:
  %(prog)s --ingest-only
  %(prog)s --review-only
  %(prog)s --materialize-only
  %(prog)s --status
  %(prog)s --candidates
  %(prog)s --health
        """,
    )
    parser.add_argument("command", nargs="?", choices=["run", "status", "candidates", "health", "backup"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--run", action="store_true", help="Run a workflow (default)")
    parser.add_argument("--workflow", choices=knowledge_workflows.supported_workflows(), default="full_cycle")
    parser.add_argument("--date", type=str, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--run-id", help="Explicit durable run id")
    parser.add_argument("--resume", help="Resume an existing durable run id")
    parser.add_argument("--retry-failed", help="Retry from the first failed step in an existing run id")
    parser.add_argument("--from-step", help="Start at a named workflow step")
    parser.add_argument("--max-attempts", type=int, default=1, help="Attempts per step")
    parser.add_argument("--ingest-only", action="store_true", help="Legacy alias for daily_ingest_and_review")
    parser.add_argument("--review-only", action="store_true", help="Legacy alias for auto_review_only")
    parser.add_argument("--materialize-only", action="store_true", help="Legacy alias for materialize_only")
    parser.add_argument("--status", action="store_true", help="Show execution status")
    parser.add_argument("--candidates", nargs="?", const="TODAY", help="Show candidate queue")
    parser.add_argument("--health", action="store_true", help="Health check (last 3 days)")
    parser.add_argument("--backup", action="store_true", help="Create a SQLite backup")
    return parser


def resolve_action(args: argparse.Namespace) -> tuple[str, str | None, str | None]:
    target_date = args.date or default_target_date()

    if getattr(args, "health", False) or args.command == "health":
        return ("health", None, None)
    if getattr(args, "backup", False) or args.command == "backup":
        return ("backup", None, target_date)
    if getattr(args, "status", False) or args.command == "status":
        status_date = args.date or args.value or default_target_date()
        return ("status", None, status_date)
    if getattr(args, "candidates", None) is not None or args.command == "candidates":
        if getattr(args, "candidates", None) is not None:
            candidate_date = default_target_date() if args.candidates == "TODAY" else args.candidates
        else:
            candidate_date = args.date or args.value or default_target_date()
        return ("candidates", None, candidate_date)
    if getattr(args, "ingest_only", False):
        return ("run", "daily_ingest_and_review", target_date)
    if getattr(args, "review_only", False):
        return ("run", "auto_review_only", target_date)
    if getattr(args, "materialize_only", False):
        return ("run", "materialize_only", target_date)
    if args.command == "run" or getattr(args, "run", False):
        return ("run", args.workflow, target_date)
    return ("run", args.workflow, target_date)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    action, workflow_name, target_date = resolve_action(args)

    if action == "health":
        health_check()
        return
    if action == "backup":
        backup_database(target_date or default_target_date())
        return
    if action == "status":
        show_status(target_date or default_target_date())
        return
    if action == "candidates":
        show_candidates(target_date or default_target_date())
        return

    advanced = args.run_id or args.resume or args.retry_failed or args.from_step or args.max_attempts != 1
    if advanced:
        run_workflow(
            workflow_name or "full_cycle",
            target_date or default_target_date(),
            run_id=args.run_id,
            resume_run_id=args.resume,
            retry_failed_run_id=args.retry_failed,
            from_step=args.from_step,
            max_attempts=args.max_attempts,
        )
        return

    run_workflow(workflow_name or "full_cycle", target_date or default_target_date())


if __name__ == "__main__":
    main()
