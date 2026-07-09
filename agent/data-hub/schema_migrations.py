from __future__ import annotations

import sqlite3


SUMMARY_LEVELS_WITH_DAILY = "'daily', 'weekly', 'monthly', 'quarterly', 'yearly'"


def ensure_summary_runs_allows_daily(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'summary_runs'"
    ).fetchone()
    if not row or "summary_level" not in row["sql"]:
        return
    if "'daily'" in row["sql"]:
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(
            f"""
            CREATE TABLE summary_runs_new (
                id TEXT PRIMARY KEY,
                summary_level TEXT NOT NULL CHECK(summary_level IN ({SUMMARY_LEVELS_WITH_DAILY})),
                period_id TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                source_mode TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
                output_path TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{{}}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO summary_runs_new
                (id, summary_level, period_id, period_start, period_end, source_mode, status,
                 output_path, metadata_json, created_at, updated_at)
            SELECT
                id, summary_level, period_id, period_start, period_end, source_mode, status,
                output_path, metadata_json, created_at, updated_at
            FROM summary_runs;
            DROP TABLE summary_runs;
            ALTER TABLE summary_runs_new RENAME TO summary_runs;
            CREATE INDEX IF NOT EXISTS idx_summary_runs_level_period
                ON summary_runs(summary_level, period_id);
            CREATE INDEX IF NOT EXISTS idx_summary_runs_status
                ON summary_runs(status, updated_at DESC);
            """
        )
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
