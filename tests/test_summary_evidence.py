from __future__ import annotations

from pathlib import Path
import sys


CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR.parent / "agent" / "data-hub"))

from summary_evidence import collect_summary_evidence


class FakeLlmWiki:
    def chat(self, message: str, *, mode: str):
        assert "2026-07-10" in message
        assert mode == "deep"
        return {
            "message": "A reusable finding",
            "citations": [
                {"path": "40_Knowledge/ADR/data-hub.md", "title": "Data Hub ADR"},
                {"path": "70_Summaries/Weekly/2026-W28.md", "title": "old summary"},
            ],
        }


def test_collect_summary_evidence_is_deterministic_and_excludes_summary_as_source():
    packet = {
        "local_markdown": {
            "daily": [{"path": "10_Periodic/Daily/2026-07-10.md", "snippet": "Closed a migration."}],
            "adrs": [{"path": "40_Knowledge/ADR/data-hub.md", "snippet": "SQLite is canonical."}],
            "cards": [],
        },
        "open_loops": [{"candidate_id": "cand-1", "title": "Verify schedule"}],
    }

    first = collect_summary_evidence(
        level="daily",
        period="2026-07-10",
        query="data hub progress",
        retrieval_packet=packet,
        llm_wiki_client=FakeLlmWiki(),
    )
    second = collect_summary_evidence(
        level="daily",
        period="2026-07-10",
        query="data hub progress",
        retrieval_packet=packet,
        llm_wiki_client=FakeLlmWiki(),
    )

    assert first["quality_status"] == "complete"
    assert first["evidence_groups"] == second["evidence_groups"]
    refs = {ref for group in first["evidence_groups"] for ref in group["source_refs"]}
    assert "70_Summaries/Weekly/2026-W28.md" not in refs
    assert "40_Knowledge/ADR/data-hub.md" in refs
    assert first["deep_research"]["message"] == "A reusable finding"


def test_collect_summary_evidence_degrades_when_deep_research_is_unavailable():
    packet = {"local_markdown": {"daily": [], "adrs": [], "cards": []}, "open_loops": []}

    result = collect_summary_evidence(
        level="daily",
        period="2026-07-10",
        query="data hub progress",
        retrieval_packet=packet,
        llm_wiki_client=None,
    )

    assert result["quality_status"] == "degraded"
    assert result["warnings"] == ["llm_wiki deep research unavailable"]
