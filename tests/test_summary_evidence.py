from __future__ import annotations

from pathlib import Path
import sys


CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR.parent / "data-hub"))

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


def test_work_evidence_keeps_confirmed_sources_and_rejects_empty_or_pending_as_work():
    packet = {
        "local_markdown": {
            "daily": [
                {"path": "10_Periodic/Daily/empty.md", "snippet": ""},
                {"path": "10_Periodic/Daily/full.md", "snippet": "Completed migration."},
            ],
            "adrs": [],
            "cards": [],
        },
        "git_commits": [{"hash": "abc123", "subject": "Ship summary engine"}],
        "knowledge_records": [
            {"id": "rec-1", "status": "accepted", "content": "Confirmed decision."},
            {"id": "rec-2", "status": "pending", "content": "Not confirmed."},
        ],
        "accepted_candidates": [
            {"id": "cand-1", "status": "accepted", "content": "Accepted evidence."},
        ],
        "open_loops": [{"candidate_id": "open-1", "status": "pending", "title": "Investigate"}],
    }

    result = collect_summary_evidence(
        level="daily",
        period="2026-07-10",
        query="summary engine",
        retrieval_packet=packet,
        llm_wiki_client=None,
    )

    kinds = {kind for group in result["evidence_groups"] for kind in group["source_kinds"]}
    refs = {ref for group in result["evidence_groups"] for ref in group["source_refs"]}
    assert {"daily_note", "git_commit", "knowledge_record", "accepted_candidate", "pending_candidate"} <= kinds
    assert "10_Periodic/Daily/empty.md" not in refs
    assert "record:rec-2" not in refs


def test_evidence_payload_compacts_repeated_and_oversized_record_content():
    repeated = "该记录以中文归档，便于后续检索与复盘。" * 200
    packet = {
        "local_markdown": {"daily": [], "adrs": [], "cards": []},
        "knowledge_records": [
            {
                "id": "rec-large",
                "status": "accepted",
                "content": "已完成 Summary Engine 验收。" + repeated,
            }
        ],
    }

    result = collect_summary_evidence(
        level="daily",
        period="2026-07-10",
        query="summary engine",
        retrieval_packet=packet,
        llm_wiki_client=None,
    )

    content = result["evidence_groups"][0]["payload"]["content"]
    assert len(content) <= 1600
    assert content.count("该记录以中文归档") == 1
    assert len(result["evidence_groups"][0]["source_payload_sha256"]) == 64


def test_evidence_id_tracks_full_source_while_only_prose_fields_are_compacted():
    common = "A" * 2000

    def collect(tail: str):
        return collect_summary_evidence(
            level="daily",
            period="2026-07-10",
            query="summary engine",
            retrieval_packet={
                "local_markdown": {"daily": [], "adrs": [], "cards": []},
                "knowledge_records": [
                    {
                        "id": "rec.with punctuation!?",
                        "status": "accepted",
                        "title": "Metadata\nkeeps formatting",
                        "content": common + tail,
                    }
                ],
            },
            llm_wiki_client=None,
        )["evidence_groups"][0]

    first = collect("结论A。")
    second = collect("结论B。")

    assert first["evidence_group_id"] != second["evidence_group_id"]
    assert first["source_payload_sha256"] != second["source_payload_sha256"]
    assert first["payload"]["id"] == "rec.with punctuation!?"
    assert first["payload"]["status"] == "accepted"
    assert first["payload"]["title"] == "Metadata\nkeeps formatting"
    assert first["payload"]["content"].endswith("结论A。")


def test_long_subject_is_compacted_without_overwriting_source_metadata():
    result = collect_summary_evidence(
        level="daily",
        period="2026-07-10",
        query="summary engine",
        retrieval_packet={
            "local_markdown": {"daily": [], "adrs": [], "cards": []},
            "git_commits": [
                {
                    "hash": "abc123",
                    "subject": "S" * 2000,
                    "source_payload_sha256": "source-owned-value",
                }
            ],
        },
        llm_wiki_client=None,
    )["evidence_groups"][0]

    assert len(result["payload"]["subject"]) <= 1600
    assert result["payload"]["source_payload_sha256"] == "source-owned-value"
    assert len(result["source_payload_sha256"]) == 64
