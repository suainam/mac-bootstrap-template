"""Reporting and backup helpers for the knowledge lifecycle manager."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable


def table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def show_status(target_date: str, *, load_env: Callable[[], None], get_db_connection: Callable) -> None:
    load_env()
    conn = get_db_connection()
    if table_exists(conn, "workflow_runs") and _print_workflow_runs(conn, target_date):
        return
    _print_legacy_status(conn, target_date)


def _print_workflow_runs(conn, target_date: str) -> bool:
    runs = conn.execute(
        """
        SELECT id, workflow_name, status, started_at, completed_at, error_message
        FROM workflow_runs
        WHERE target_date = ?
        ORDER BY started_at DESC
        LIMIT 5
        """,
        (target_date,),
    ).fetchall()
    if not runs:
        return False

    print(f"\nWorkflow Runs for {target_date}\n")
    for run in runs:
        print(f"{run['id']}  {run['workflow_name']}  {run['status']}  {run['started_at']}")
        steps = conn.execute(
            """
            SELECT step_index, step_name, status, attempt, exit_code, error_message
            FROM workflow_steps
            WHERE run_id = ?
            ORDER BY step_index ASC
            """,
            (run["id"],),
        ).fetchall()
        for step in steps:
            error = (step["error_message"] or "")[:60]
            print(
                f"  {step['step_index'] + 1:02d}. {step['step_name']:<35} "
                f"{step['status']:<10} attempts={step['attempt']} exit={step['exit_code']} {error}"
            )
    conn.close()
    print()
    return True


def _print_legacy_status(conn, target_date: str) -> None:
    rows = conn.execute(
        """
        SELECT step_name, started_at, completed_at, status, records_affected, error_message
        FROM execution_log
        WHERE execution_date = ?
        ORDER BY started_at ASC
        """,
        (target_date,),
    ).fetchall()
    if not rows:
        print(f"No execution logs found for {target_date}")
        conn.close()
        return

    print(f"\nExecution Status for {target_date}\n")
    print(f"{'Step':<25} {'Status':<10} {'Records':<10} {'Duration':<12} {'Error'}")
    print("-" * 90)
    for row in rows:
        step, started, completed, status, records, error = row
        duration = _duration(started, completed)
        status_icon = {"completed": "OK", "failed": "FAIL", "running": "RUN"}.get(status, "UNK")
        error_msg = error[:40] if error else ""
        print(f"{step:<25} {status_icon} {status:<8} {records:<10} {duration:<12} {error_msg}")

    conn.close()
    print()


def show_candidates(target_date: str, *, load_env: Callable[[], None], get_db_connection: Callable) -> None:
    load_env()
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT status, candidate_type, COUNT(*) as count
        FROM knowledge_candidates
        WHERE candidate_date = ?
        GROUP BY status, candidate_type
        ORDER BY status, candidate_type
        """,
        (target_date,),
    ).fetchall()
    if not rows:
        print(f"No candidates found for {target_date}")
        conn.close()
        return

    print(f"\nCandidate Queue for {target_date}\n")
    print(f"{'Status':<12} {'Type':<15} {'Count'}")
    print("-" * 40)
    total_by_status: dict[str, int] = {}
    for status, candidate_type, count in rows:
        print(f"{status:<12} {candidate_type:<15} {count}")
        total_by_status[status] = total_by_status.get(status, 0) + count
    print("-" * 40)
    for status, total in sorted(total_by_status.items()):
        print(f"{'Total':<12} {status:<15} {total}")
    conn.close()
    print()


def health_check(*, load_env: Callable[[], None], get_db_connection: Callable) -> None:
    load_env()
    conn = get_db_connection()
    dates = [(datetime.now().date() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
    failed_runs, stale_runs = _workflow_health_rows(conn, dates)
    legacy_rows = _legacy_failed_rows(conn, dates)

    if not legacy_rows and not failed_runs and not stale_runs:
        print("\nHealth Check: All clear (last 3 days)\n")
        conn.close()
        return

    _print_health_summary(failed_runs, stale_runs, legacy_rows)
    conn.close()


def _workflow_health_rows(conn, dates: list[str]) -> tuple[list, list]:
    if not table_exists(conn, "workflow_runs"):
        return [], []
    failed_runs = conn.execute(
        """
        SELECT id, workflow_name, target_date, error_message
        FROM workflow_runs
        WHERE target_date IN (?, ?, ?) AND status = 'failed'
        ORDER BY started_at DESC
        """,
        tuple(dates),
    ).fetchall()
    stale_runs = conn.execute(
        """
        SELECT id, workflow_name, target_date, started_at
        FROM workflow_runs
        WHERE status = 'running' AND started_at < ?
        ORDER BY started_at ASC
        """,
        ((datetime.now() - timedelta(hours=6)).isoformat(timespec="seconds"),),
    ).fetchall()
    return failed_runs, stale_runs


def _legacy_failed_rows(conn, dates: list[str]) -> list:
    return conn.execute(
        """
        SELECT execution_date, step_name, status, error_message
        FROM execution_log
        WHERE execution_date IN (?, ?, ?) AND status = 'failed'
        ORDER BY execution_date DESC, started_at DESC
        """,
        tuple(dates),
    ).fetchall()


def _print_health_summary(failed_runs: list, stale_runs: list, legacy_rows: list) -> None:
    print(
        f"\nHealth Check: {len(failed_runs)} failed runs, "
        f"{len(legacy_rows)} failed legacy steps in last 3 days, {len(stale_runs)} stale runs\n"
    )
    if legacy_rows:
        print(f"{len(legacy_rows)} failed steps in last 3 days")
    if failed_runs:
        print(f"{'Run ID':<24} {'Date':<12} {'Workflow':<28} {'Error'}")
        print("-" * 90)
        for run in failed_runs:
            error_msg = (run["error_message"] or "Unknown error")[:50]
            print(f"{run['id']:<24} {run['target_date']:<12} {run['workflow_name']:<28} {error_msg}")
        print()
    if stale_runs:
        print("Stale running workflows:")
        for run in stale_runs:
            print(f"{run['id']} {run['target_date']} {run['workflow_name']} started={run['started_at']}")
        print()
    if legacy_rows:
        _print_legacy_failures(legacy_rows)


def _print_legacy_failures(rows: list) -> None:
    print("Legacy execution_log failures:\n")
    print(f"{'Date':<12} {'Step':<25} {'Error'}")
    print("-" * 80)
    for date, step, _status, error in rows:
        error_msg = error[:50] if error else "Unknown error"
        print(f"{date:<12} {step:<25} {error_msg}")
    print()


def backup_database(
    target_date: str,
    *,
    db_path: Path,
    load_env: Callable[[], None],
    get_db_connection: Callable,
) -> None:
    load_env()
    conn = get_db_connection()
    backup_path = _backup_path(db_path, target_date)
    backup_id = f"backup_{hashlib.sha1(str(backup_path).encode('utf-8')).hexdigest()[:16]}"
    try:
        with sqlite3.connect(backup_path) as dest:
            conn.backup(dest)
        digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
        _record_backup(conn, backup_id, backup_path, digest)
        print(f"Backup completed: {backup_path}")
        print(f"sha256: {digest}")
    except Exception as exc:
        _record_backup_failure(conn, backup_id, backup_path, exc)
        raise
    finally:
        conn.close()


def _backup_path(db_path: Path, target_date: str) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir / f"agent_history-{target_date}-{datetime.now().strftime('%H%M%S')}.db"


def _record_backup(conn, backup_id: str, backup_path: Path, digest: str) -> None:
    conn.execute(
        """
        INSERT INTO backup_log
            (id, backup_path, content_hash, created_at, status, metadata_json)
        VALUES (?, ?, ?, ?, 'completed', '{}')
        """,
        (backup_id, str(backup_path), digest, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def _record_backup_failure(conn, backup_id: str, backup_path: Path, exc: Exception) -> None:
    conn.execute(
        """
        INSERT INTO backup_log
            (id, backup_path, content_hash, created_at, status, error_message, metadata_json)
        VALUES (?, ?, '', ?, 'failed', ?, '{}')
        """,
        (backup_id, str(backup_path), datetime.now().isoformat(timespec="seconds"), str(exc)),
    )
    conn.commit()


def _duration(started: str | None, completed: str | None) -> str:
    if not started or not completed:
        return ""
    start_dt = datetime.fromisoformat(started)
    end_dt = datetime.fromisoformat(completed)
    return f"{(end_dt - start_dt).total_seconds():.1f}s"
