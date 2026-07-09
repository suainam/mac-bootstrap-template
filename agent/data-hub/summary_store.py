from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def stable_summary_run_id(level: str, period_start: str, period_end: str, source_mode: str) -> str:
    digest = hashlib.sha1(f"{level}:{period_start}:{period_end}:{source_mode}".encode("utf-8")).hexdigest()[:16]
    return f"sum_{digest}"


def start_summary_run(
    conn: sqlite3.Connection,
    *,
    level: str,
    period_id: str,
    period_start: str,
    period_end: str,
    source_mode: str,
) -> str:
    run_id = stable_summary_run_id(level, period_start, period_end, source_mode)
    now = now_iso()
    conn.execute(
        """
        INSERT INTO summary_runs
            (id, summary_level, period_id, period_start, period_end, source_mode, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status = 'running',
            output_path = NULL,
            metadata_json = '{}',
            updated_at = excluded.updated_at
        """,
        (run_id, level, period_id, period_start, period_end, source_mode, now, now),
    )
    conn.execute("DELETE FROM summary_run_sources WHERE run_id = ?", (run_id,))
    conn.commit()
    return run_id


def record_summary_sources(conn: sqlite3.Connection, run_id: str, sources: list[dict[str, Any]]) -> None:
    for source in sources:
        conn.execute(
            """
            INSERT INTO summary_run_sources (run_id, source_kind, source_ref, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                run_id,
                str(source["source_kind"]),
                str(source["source_ref"]),
                json.dumps(source.get("metadata", {}), ensure_ascii=False, sort_keys=True),
            ),
        )
    conn.commit()


def complete_summary_run(
    conn: sqlite3.Connection,
    run_id: str,
    output_path: str,
    metadata: dict[str, Any],
    *,
    status: str = "completed",
) -> None:
    conn.execute(
        """
        UPDATE summary_runs
        SET status = ?, output_path = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            status,
            output_path,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            now_iso(),
            run_id,
        ),
    )
    conn.commit()
