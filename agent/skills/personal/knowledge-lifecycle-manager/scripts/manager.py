#!/usr/bin/env python3
"""Knowledge Lifecycle Manager - Unified data-hub pipeline control."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime
from pathlib import Path


def resolve_template_root(script_path: Path) -> Path:
    for candidate in script_path.parents:
        if (candidate / "agent" / "data-hub").is_dir():
            return candidate
        nested_template = candidate / "template"
        if (nested_template / "agent" / "data-hub").is_dir():
            return nested_template
    raise RuntimeError(f"Unable to resolve template root from {script_path}")


TEMPLATE_ROOT = resolve_template_root(Path(__file__).resolve())
DATA_HUB = TEMPLATE_ROOT / "agent" / "data-hub"
PYTHON = TEMPLATE_ROOT / ".venv" / "bin" / "python"
LOCAL_SCRIPTS_DIR = Path(__file__).resolve().parent
KNOWLEDGE_RECORD_SCRIPT = (
    TEMPLATE_ROOT
    / "agent"
    / "skills"
    / "personal"
    / "knowledge-record"
    / "scripts"
    / "record_knowledge.py"
)

sys.path.insert(0, str(LOCAL_SCRIPTS_DIR))
sys.path.insert(0, str(DATA_HUB))
from data_hub_config import get_runtime_config
from db_helper import get_db_connection
import knowledge_workflows
import manager_reporting


def load_record_knowledge_module():
    spec = importlib.util.spec_from_file_location(
        "knowledge_record_impl",
        KNOWLEDGE_RECORD_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


record_knowledge = load_record_knowledge_module()


def default_target_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_env() -> None:
    return None


def _db_path_from_env() -> Path:
    return get_runtime_config().paths.db_path


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


def record_knowledge_entry(args: argparse.Namespace, target_date: str) -> None:
    """Record a live agent knowledge item through the unified manager."""
    if getattr(args, "suggest", False):
        suggest_args = [
            "suggest",
            "--date",
            target_date,
        ]
        optional_pairs = [
            ("--agent", args.agent),
            ("--project-path", args.project_path),
            ("--db-path", args.db_path),
            ("--thread-json", args.thread_json),
            ("--thread-summary", args.thread_summary),
        ]
        for flag, value in optional_pairs:
            if value:
                suggest_args.extend([flag, value])
        for action in args.action or []:
            suggest_args.extend(["--action", action])
        raise SystemExit(record_knowledge.main(suggest_args))

    record_args = [
        "--type",
        args.record_type,
        "--title",
        args.title,
        "--content",
        args.content,
        "--date",
        target_date,
    ]
    optional_pairs = [
        ("--background", args.background),
        ("--tags", args.tags),
        ("--impact", args.impact),
        ("--references", args.references),
        ("--project", args.project),
        ("--expires-at", args.expires_at),
        ("--why-record", args.why_record),
        ("--agent", args.agent),
        ("--session-id", args.session_id),
        ("--message-id", str(args.message_id) if args.message_id is not None else None),
        ("--project-path", args.project_path),
        ("--db-path", args.db_path),
    ]
    for flag, value in optional_pairs:
        if value:
            record_args.extend([flag, value])
    if args.is_actionable:
        record_args.append("--is-actionable")
    if args.dry_run:
        record_args.append("--dry-run")
    raise SystemExit(record_knowledge.main(record_args))


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
  %(prog)s record --type adr --title "..." --content "..."
  %(prog)s --status
  %(prog)s --candidates
  %(prog)s --health
        """,
    )
    parser.add_argument("command", nargs="?", choices=["run", "status", "candidates", "health", "backup", "record"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--run", action="store_true", help="Run a workflow (default)")
    parser.add_argument("--workflow", choices=knowledge_workflows.supported_workflows(), default="full_cycle")
    parser.add_argument("--date", type=str, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--run-id", help="Explicit durable run id")
    parser.add_argument("--resume", help="Resume an existing durable run id")
    parser.add_argument("--retry-failed", help="Retry from the first failed step in an existing run id")
    parser.add_argument("--from-step", help="Start at a named workflow step")
    parser.add_argument("--max-attempts", type=int, default=1, help="Attempts per step")
    parser.add_argument("--status", action="store_true", help="Show execution status")
    parser.add_argument("--candidates", nargs="?", const="TODAY", help="Show candidate queue")
    parser.add_argument("--health", action="store_true", help="Health check (last 3 days)")
    parser.add_argument("--backup", action="store_true", help="Create a SQLite backup")
    parser.add_argument("--type", dest="record_type", choices=["adr", "card", "daily"], help="Record type for record command")
    parser.add_argument("--title", help="Knowledge title for record command")
    parser.add_argument("--content", help="Knowledge content for record command")
    parser.add_argument("--background")
    parser.add_argument("--tags")
    parser.add_argument("--impact", choices=["high", "medium", "low"])
    parser.add_argument("--is-actionable", action="store_true")
    parser.add_argument("--references")
    parser.add_argument("--project")
    parser.add_argument("--expires-at")
    parser.add_argument("--why-record")
    parser.add_argument("--agent")
    parser.add_argument("--session-id")
    parser.add_argument("--message-id", type=int)
    parser.add_argument("--project-path")
    parser.add_argument("--db-path")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--suggest", action="store_true", help="Suggest and confirm a knowledge record")
    parser.add_argument(
        "--action",
        action="append",
        help="Confirmation action for record --suggest; repeat for edit/regenerate/accept flows",
    )
    parser.add_argument("--thread-json", help="Current agent thread JSON for record --suggest")
    parser.add_argument("--thread-summary", help="Current agent thread summary for record --suggest")
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
    if args.command == "record":
        return ("record", None, target_date)
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
    if action == "record":
        if not args.suggest and (not args.record_type or not args.title or not args.content):
            parser.error("record requires --type, --title, and --content")
        record_knowledge_entry(args, target_date or default_target_date())
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
