from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace


DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "agent" / "data-hub"
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
    def __init__(self, level: str, period: str):
        self.level = level
        self.period = period
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
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
        repeat = 9 if self.level == "weekly" else 6
        prose = "这是经过证据验证、能够影响后续决策并可复用的明确结论。" * repeat
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

    original_hash = full_file_sha256(results["daily"].output_path)
    conn = get_db_connection(db_path)
    try:
        original_count = conn.execute("SELECT COUNT(*) FROM summary_revisions").fetchone()[0]
    finally:
        conn.close()

    repeated_backend = StructuredBackend("daily", periods["daily"])
    repeated = period_summary.build_period_summary(
        "daily",
        "2026-12-31",
        backend=repeated_backend,
        retrieval_packet=packet,
        llm_wiki_client=StableDeepClient(),
    )
    conn = get_db_connection(db_path)
    try:
        repeated_count = conn.execute("SELECT COUNT(*) FROM summary_revisions").fetchone()[0]
    finally:
        conn.close()

    assert repeated.revision_id == results["daily"].revision_id
    assert repeated_backend.calls == 0
    assert repeated_count == original_count == 5
    assert full_file_sha256(repeated.output_path) == original_hash
