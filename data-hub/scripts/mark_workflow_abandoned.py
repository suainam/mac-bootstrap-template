#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent
if str(DATA_HUB_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_HUB_DIR))

from db_helper import get_db_connection


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mark_workflow_abandoned(conn: sqlite3.Connection, run_id: str, reason: str) -> None:
    completed_at = now_iso()
    conn.execute(
        """
        UPDATE workflow_runs
        SET status = 'failed', completed_at = ?, error_message = ?
        WHERE id = ? AND status = 'running'
        """,
        (completed_at, reason, run_id),
    )
    conn.execute(
        """
        UPDATE workflow_steps
        SET status = 'failed', completed_at = ?, error_message = ?
        WHERE run_id = ? AND status = 'running'
        """,
        (completed_at, reason, run_id),
    )
    conn.commit()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mark an interrupted workflow run as failed/abandoned.")
    parser.add_argument("run_id")
    parser.add_argument("--reason", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    conn = get_db_connection()
    try:
        mark_workflow_abandoned(conn, args.run_id, args.reason)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
