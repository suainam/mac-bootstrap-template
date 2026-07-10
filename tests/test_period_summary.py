from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
import re

DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

import period_summary
from db_helper import get_db_connection
from period_summary import resolve_period_coverage


def test_weekly_preholiday_revision_is_provisional_before_week_end():
    result = resolve_period_coverage("weekly", "2026-10-02")

    assert result.period_id == "2026-W40"
    assert result.closure_status == "provisional"
    assert result.coverage_end == "2026-10-02"


def test_daily_coverage_is_closed():
    result = resolve_period_coverage("daily", "2026-07-10")

    assert result.closure_status == "closed"
    assert result.period_start == result.coverage_end


class JsonBackend:
    def generate(self, prompt):
        evidence_id = re.search(r'evg_[A-Za-z0-9_]+', prompt).group(0)
        detailed = "可验证进展已经完成并可复用。" * 16
        return (
            '{"contract_version":"summary-v1","taxonomy_version":"dimensions-v1",'
            '"policy_version":"summary-policy-v1","level":"daily","period":"2026-07-10",'
            f'"headline":"{detailed}","items":[{{"item_type":"outcome","title":"{detailed}",'
            f'"conclusion":"{detailed}","value":"{detailed}","dimensions":["专业知识"],'
            f'"evidence_group_ids":["{evidence_id}"],"confidence":0.9}}]}}'
        )


def test_build_daily_summary_publishes_revisioned_markdown(monkeypatch, tmp_path):
    db_path = tmp_path / "db.sqlite"
    monkeypatch.setattr(period_summary, "get_db_connection", lambda: get_db_connection(db_path))
    monkeypatch.setattr(period_summary, "get_summary_output_dir", lambda _level: tmp_path / "70_Summaries" / "Daily")
    monkeypatch.setattr(period_summary, "get_runtime_config", lambda: SimpleNamespace(summary=SimpleNamespace(deployment_start="2026-07-01")))
    packet = {"local_markdown": {"daily": [{"path": "10_Periodic/Daily/2026-07-10.md", "title": "daily", "snippet": "evidence"}], "adrs": [], "cards": []}, "open_loops": []}

    result = period_summary.build_period_summary("daily", "2026-07-10", backend=JsonBackend(), retrieval_packet=packet, llm_wiki_client=None)

    assert result.quality_status == "degraded"
    text = result.output_path.read_text(encoding="utf-8")
    assert "revision_id:" in text
    conn = get_db_connection(db_path)
    try:
        assert conn.execute("SELECT publish_status FROM summary_revisions").fetchone()[0] == "published"
    finally:
        conn.close()
