#!/usr/bin/env python3
"""
Agent Data Hub - Health Check Script

Reads execution logs from the last 3 days and reports failed steps.
Optional osascript notifications when ENABLE_NOTIFICATIONS=true.

Usage:
    python health_check.py

Codex CronCreate configuration:
    Time: Every day at 18:10
    Command: python $HOME/work/config/mac-bootstrap/template/agent/data-hub/health_check.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from db_helper import get_db_connection


def get_failed_executions(days: int = 3) -> list[dict]:
    """Get failed execution logs from the last N days."""
    conn = get_db_connection()
    try:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        cursor = conn.execute(
            """
            SELECT execution_date, step_name, started_at, completed_at, error_message
            FROM execution_log
            WHERE execution_date >= DATE(?) AND status = 'failed'
            ORDER BY execution_date DESC, started_at DESC
            """,
            (start_date,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def format_report(failed_logs: list[dict]) -> str:
    """Format failed logs into a human-readable report."""
    if not failed_logs:
        return "✅ All pipeline steps succeeded in the last 3 days."

    report_lines = [
        "⚠️  Pipeline Health Check Report",
        f"Failed steps in the last 3 days: {len(failed_logs)}",
        "",
    ]

    for log in failed_logs:
        report_lines.append(f"Date: {log['execution_date']}")
        report_lines.append(f"Step: {log['step_name']}")
        report_lines.append(f"Started: {log['started_at']}")
        report_lines.append(f"Completed: {log['completed_at']}")
        report_lines.append(f"Error: {log['error_message']}")
        report_lines.append("")

    return "\n".join(report_lines)


def send_notification(message: str) -> None:
    """Send macOS notification using osascript."""
    if os.environ.get("ENABLE_NOTIFICATIONS", "").lower() != "true":
        return

    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "Agent Data Hub Health Check"',
            ],
            check=False,
            timeout=5,
        )
    except Exception as e:
        print(f"Failed to send notification: {e}", file=sys.stderr)


def main() -> None:
    failed_logs = get_failed_executions(days=3)
    report = format_report(failed_logs)
    print(report)

    if failed_logs:
        send_notification(f"Found {len(failed_logs)} failed pipeline steps")


if __name__ == "__main__":
    main()

