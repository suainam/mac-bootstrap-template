from __future__ import annotations

import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent / "agent" / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

import data_hub_config
import period_summary
from db_helper import get_db_connection


def configure_runtime(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "agent_history.db"
    vault_dir = tmp_path / "knowledge"
    runtime = tmp_path / "private" / "agent" / "data_hub.runtime.jsonc"
    runtime.parent.mkdir(parents=True)
    monkeypatch.setattr(data_hub_config, "RUNTIME_CONFIG", runtime)
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("OBSIDIAN_VAULT_DIR", str(vault_dir))
    return db_path, vault_dir


def test_render_summary_note_uses_quarantine_frontmatter():
    note = period_summary.render_summary_note(
        level="weekly",
        period_id="2026-W28",
        body="- shipped summary\n",
        derived_from={
            "daily": ["10_Periodic/Daily/2026-07-09.md"],
            "sqlite_records": ["rec_1"],
            "llm_wiki_context": ["wiki/projects/data-hub.md"],
        },
    )

    assert "summary_level: weekly" in note
    assert "indexing: excluded" in note
    assert "source_mode: daily-first" in note
    assert "# Weekly Summary 2026-W28" in note


def test_build_period_summary_writes_70_summaries_and_lineage(monkeypatch, tmp_path: Path):
    db_path, vault_dir = configure_runtime(monkeypatch, tmp_path)
    daily = vault_dir / "10_Periodic" / "Daily" / "2026-07-09.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-07-09\n\nBuilt data-hub dual-system summary.\n", encoding="utf-8")

    monkeypatch.setattr(
        period_summary,
        "build_retrieval_packet",
        lambda **kwargs: {
            "local_markdown": {
                "daily": [{"path": "10_Periodic/Daily/2026-07-09.md", "title": "2026-07-09", "score": 2}],
                "adrs": [],
                "cards": [],
            },
            "open_loops": [{"candidate_id": "cand_1", "title": "Check summary loop"}],
            "llm_wiki_context": {
                "results": [{"path": "wiki/projects/data-hub.md", "title": "data-hub"}],
                "warnings": [],
            },
            "reuse_recommendations": ["Reuse daily-first evidence."],
        },
    )

    output_path = period_summary.build_period_summary("weekly", "2026-07-09")

    assert output_path == vault_dir / "70_Summaries" / "Weekly" / "2026-W28.md"
    assert "promotion_status: not_reviewed" in output_path.read_text(encoding="utf-8")
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT output_path FROM summary_runs").fetchone()
        source_count = conn.execute("SELECT COUNT(*) FROM summary_run_sources").fetchone()[0]
    finally:
        conn.close()
    assert row["output_path"] == "70_Summaries/Weekly/2026-W28.md"
    assert source_count == 3
    assert db_path.exists()
