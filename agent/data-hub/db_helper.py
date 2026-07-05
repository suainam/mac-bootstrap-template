"""Database helper with common connection and queries."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from data_hub_config import get_db_path


def get_db_connection() -> sqlite3.Connection:
    """Get DB connection from AGENT_DB_PATH env var."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema_path = Path(__file__).parent / "schema.sql"
    conn.executescript(schema_path.read_text())
    return conn


def query_candidates_by_date(conn: sqlite3.Connection, target_date: str, status: str | None = None) -> list[dict]:
    """Query candidates for a given date and optionally status."""
    if status:
        cursor = conn.execute(
            """
            SELECT * FROM knowledge_candidates
            WHERE candidate_date = ? AND status = ?
            ORDER BY candidate_type, confidence DESC
            """,
            (target_date, status),
        )
    else:
        cursor = conn.execute(
            """
            SELECT * FROM knowledge_candidates
            WHERE candidate_date = ?
            ORDER BY candidate_type, confidence DESC
            """,
            (target_date,),
        )
    return [dict(row) for row in cursor.fetchall()]


def query_execution_log(conn: sqlite3.Connection, execution_date: str) -> list[dict]:
    """Query execution log for a given date."""
    cursor = conn.execute(
        """
        SELECT * FROM execution_log
        WHERE execution_date = ?
        ORDER BY started_at ASC
        """,
        (execution_date,),
    )
    return [dict(row) for row in cursor.fetchall()]


def query_sessions_count(conn: sqlite3.Connection) -> int:
    """Get total sessions count."""
    return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


def query_messages_count(conn: sqlite3.Connection) -> int:
    """Get total messages count."""
    return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


def query_source_documents_count(conn: sqlite3.Connection) -> int:
    """Get total source documents count."""
    return conn.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]


def query_candidates_count(conn: sqlite3.Connection) -> int:
    """Get total candidates count."""
    return conn.execute("SELECT COUNT(*) FROM knowledge_candidates").fetchone()[0]
