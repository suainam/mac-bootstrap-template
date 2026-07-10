"""Execution logger for pipeline traceability."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime


class ExecutionLogger:
    """Log pipeline execution steps to SQLite execution_log table."""

    def __init__(self, conn: sqlite3.Connection, execution_date: str):
        self.conn = conn
        self.execution_date = execution_date

    def start(self, step_name: str) -> str:
        """Start a step, return log_id."""
        now = datetime.now().isoformat(timespec="microseconds")
        log_id = self._generate_id(step_name, now)
        self.conn.execute(
            """
            INSERT INTO execution_log
                (id, execution_date, step_name, started_at, status, records_affected, error_message, metadata_json)
            VALUES (?, ?, ?, ?, 'running', 0, NULL, '{}')
            """,
            (log_id, self.execution_date, step_name, now),
        )
        self.conn.commit()
        return log_id

    def complete(self, log_id: str, records_affected: int = 0, metadata: dict | None = None):
        """Mark step as completed."""
        now = datetime.now().isoformat(timespec="microseconds")
        metadata = metadata or {}
        self.conn.execute(
            """
            UPDATE execution_log
            SET completed_at = ?, status = 'completed', records_affected = ?, metadata_json = ?
            WHERE id = ?
            """,
            (now, records_affected, json.dumps(metadata, ensure_ascii=False), log_id),
        )
        self.conn.commit()

    def fail(self, log_id: str, error_message: str):
        """Mark step as failed."""
        now = datetime.now().isoformat(timespec="microseconds")
        self.conn.execute(
            """
            UPDATE execution_log
            SET completed_at = ?, status = 'failed', error_message = ?
            WHERE id = ?
            """,
            (now, error_message, log_id),
        )
        self.conn.commit()

    def get_today_logs(self) -> list[dict]:
        """Get all logs for execution_date."""
        cursor = self.conn.execute(
            """
            SELECT id, step_name, started_at, completed_at, status, records_affected, error_message, metadata_json
            FROM execution_log
            WHERE execution_date = ?
            ORDER BY started_at ASC
            """,
            (self.execution_date,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def _generate_id(self, step_name: str, started_at: str) -> str:
        """Generate stable log_id."""
        digest = hashlib.sha1(f"{self.execution_date}::{step_name}::{started_at}".encode("utf-8")).hexdigest()[:16]
        return f"log_{digest}"

