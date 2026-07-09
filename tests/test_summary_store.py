from __future__ import annotations

import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent / "agent" / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

from source_ingest_store import get_db_connection
from summary_store import complete_summary_run, record_summary_sources, start_summary_run


def test_summary_store_persists_run_and_sources(tmp_path: Path):
    conn = get_db_connection(tmp_path / "agent_history.db")
    try:
        run_id = start_summary_run(
            conn,
            level="weekly",
            period_id="2026-W28",
            period_start="2026-07-06",
            period_end="2026-07-12",
            source_mode="daily-first",
        )
        record_summary_sources(
            conn,
            run_id,
            [{"source_kind": "daily", "source_ref": "10_Periodic/Daily/2026-07-09.md"}],
        )
        complete_summary_run(conn, run_id, "70_Summaries/Weekly/2026-W28.md", {"warnings": []})

        row = conn.execute("SELECT summary_level, output_path FROM summary_runs WHERE id = ?", (run_id,)).fetchone()
        src = conn.execute("SELECT source_kind, source_ref FROM summary_run_sources WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()

    assert row["summary_level"] == "weekly"
    assert row["output_path"] == "70_Summaries/Weekly/2026-W28.md"
    assert src["source_kind"] == "daily"
