from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace


DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

import period_summary
from db_helper import get_db_connection
from summary_store import full_file_sha256


class StableDeepClient:
    def chat(self, message: str, *, mode: str):
        assert mode == "deep"
        return {
            "message": "Evidence is stable.",
            "citations": [{"path": "40_Knowledge/ADR/summary-engine.md", "content": "SQLite revisions are canonical."}],
        }


class StructuredBackend:
    def __init__(self, level: str, period: str, *, fail_on_call: bool = False):
        self.level = level
        self.period = period
        self.fail_on_call = fail_on_call
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        if self.fail_on_call:
            raise AssertionError(f"idempotent {self.level} replay must not call the backend")
        decoder = json.JSONDecoder()
        evidence_packet = None
        for index, character in enumerate(prompt):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(prompt[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and "evidence_groups" in candidate:
                evidence_packet = candidate
                break
        assert evidence_packet is not None
        evidence_ids = sorted(group["evidence_group_id"] for group in evidence_packet["evidence_groups"])
        daily_evidence_id = next(
            group["evidence_group_id"]
            for group in evidence_packet["evidence_groups"]
            if "daily_note" in group["source_kinds"]
        )
        lower_item_ids = sorted(set(re.findall(r'"(item_[a-f0-9]+)"', prompt)))
        lower_refs = sorted(set(re.findall(r'"(70_Summaries/[^"]+\.md)"', prompt)))
        repeat = 5 if self.level == "weekly" else 3
        prose_marker = f"仅属于{self.level}层且不得复制到高层的正文证据。"
        prose = (prose_marker + "这是经过验证、能够影响决策并可复用的明确结论。") * repeat
        items = []
        for item_type in ("outcome", "decision"):
            item = {
                "item_type": item_type,
                "title": prose,
                "conclusion": prose,
                "value": prose,
                "dimensions": ["计划组织", "专业知识"],
                "evidence_group_ids": [daily_evidence_id if self.level == "daily" else evidence_ids[0]],
                "confidence": 0.92,
            }
            if self.level != "daily":
                item["supporting_item_ids"] = lower_item_ids[:2]
                item["lower_summary_refs"] = lower_refs[:1]
            if self.level in {"monthly", "quarterly", "yearly"}:
                item["period_change"] = "本周期形成了可审计、可恢复、可继续聚合的稳定结构。"
            items.append(item)
        return json.dumps(
            {
                "contract_version": "summary-v1",
                "taxonomy_version": "dimensions-v1",
                "policy_version": "summary-policy-v1",
                "level": self.level,
                "period": self.period,
                "headline": prose,
                "items": items,
            },
            ensure_ascii=False,
        )


def test_five_level_summary_chain_is_idempotent(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    db_path = tmp_path / "agent_history.db"
    level_dirs = {level: level.capitalize() for level in ("daily", "weekly", "monthly", "quarterly", "yearly")}
    config = SimpleNamespace(
        paths=SimpleNamespace(vault_dir=vault, git_search_roots=[]),
        summary=SimpleNamespace(root_relative="70_Summaries", level_dirs=level_dirs, deployment_start="2026-12-31"),
    )
    monkeypatch.setattr(period_summary, "get_runtime_config", lambda: config)
    monkeypatch.setattr(period_summary, "get_db_connection", lambda: get_db_connection(db_path))
    monkeypatch.setattr(period_summary, "get_summary_output_dir", lambda level: vault / "70_Summaries" / level_dirs[level])
    packet = {
        "local_markdown": {
            "daily": [{"path": "10_Periodic/Daily/2026-12-31.md", "snippet": "Completed the structured summary engine."}],
            "adrs": [{"path": "40_Knowledge/ADR/summary-engine.md", "snippet": "SQLite is canonical."}],
            "cards": [],
        },
        "knowledge_records": [{"id": "rec-1", "status": "accepted", "content": "Confirmed summary decision."}],
        "open_loops": [],
    }
    periods = {
        "daily": "2026-12-31",
        "weekly": "2026-W53",
        "monthly": "2026-12",
        "quarterly": "2026-Q4",
        "yearly": "2026",
    }
    results = {}
    for level in ("daily", "weekly", "monthly", "quarterly", "yearly"):
        results[level] = period_summary.build_period_summary(
            level,
            "2026-12-31",
            backend=StructuredBackend(level, periods[level]),
            retrieval_packet=packet,
            llm_wiki_client=StableDeepClient(),
        )
        assert results[level].output_path.is_file()
        assert results[level].quality_status == "complete"

    original_hashes = {level: full_file_sha256(result.output_path) for level, result in results.items()}
    original_revision_ids = {level: result.revision_id for level, result in results.items()}
    conn = get_db_connection(db_path)
    try:
        original_counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "summaries",
                "summary_revisions",
                "summary_items",
                "summary_evidence_groups",
                "summary_evidence_sources",
                "summary_item_evidence",
                "summary_item_support",
            )
        }
    finally:
        conn.close()

    repeated = {}
    for level in ("daily", "weekly", "monthly", "quarterly", "yearly"):
        repeated[level] = period_summary.build_period_summary(
            level,
            "2026-12-31",
            backend=StructuredBackend(level, periods[level], fail_on_call=True),
            retrieval_packet=packet,
            llm_wiki_client=StableDeepClient(),
        )
    conn = get_db_connection(db_path)
    try:
        repeated_counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in original_counts
        }
    finally:
        conn.close()

    assert {level: result.revision_id for level, result in repeated.items()} == original_revision_ids
    assert repeated_counts == original_counts
    assert original_counts["summaries"] == original_counts["summary_revisions"] == 5
    assert {level: full_file_sha256(result.output_path) for level, result in repeated.items()} == original_hashes
    ordered_levels = ("daily", "weekly", "monthly", "quarterly", "yearly")
    for index, level in enumerate(ordered_levels[1:], start=1):
        text = repeated[level].output_path.read_text(encoding="utf-8")
        for lower_level in ordered_levels[:index]:
            assert f"仅属于{lower_level}层且不得复制到高层的正文证据。" not in text
