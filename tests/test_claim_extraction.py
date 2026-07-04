"""Tests for lifecycle stage 3 — claim_extraction.py."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(SCRIPTS_DIR))

import claim_extraction
import source_ingest_store
from source_adapters.meeting_markdown import parse as parse_meeting_markdown
from source_adapters import hash_text_file


# ---------------------------------------------------------------------------
# classify_chat_message
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_type,min_conf", [
    ("我们决定采用 filename_first 归因策略", "decision", 0.70),
    ("change to sqlite storage backend", "decision", 0.70),
    ("如何配置 clash 的 PAC 模式？", "open_loop", 0.55),
    ("why is the test failing?", "open_loop", 0.55),
    ("待办：整理 xmind 导出样例", "action", 0.60),
    ("TODO: refactor the adapter layer", "action", 0.60),
    ("风险：依赖 LLM 接口不稳定", "risk", 0.50),
    ("blocked by missing PDF dependency", "risk", 0.50),
    ("今天天气不错，休息了一下。", "insight_candidate", 0.0),
])
def test_classify_chat_message(text, expected_type, min_conf):
    claim_type, confidence = claim_extraction.classify_chat_message(text)
    assert claim_type == expected_type
    assert confidence >= min_conf


def test_classify_chat_message_confidence_in_range():
    for text in ["决定改为异步", "TODO: fix bug", "风险很高", "如何处理？", "今天完成了"]:
        _, confidence = claim_extraction.classify_chat_message(text)
        assert 0.0 <= confidence <= 1.0


# ---------------------------------------------------------------------------
# stable_id
# ---------------------------------------------------------------------------

def test_stable_id_is_deterministic():
    a = claim_extraction.stable_id("clm", "item_abc", "2026-07-04", "decision")
    b = claim_extraction.stable_id("clm", "item_abc", "2026-07-04", "decision")
    assert a == b
    assert a.startswith("clm_")


def test_stable_id_differs_by_parts():
    a = claim_extraction.stable_id("clm", "item_abc", "2026-07-04", "decision")
    b = claim_extraction.stable_id("clm", "item_abc", "2026-07-04", "action")
    assert a != b


# ---------------------------------------------------------------------------
# build_promotion_suggestions
# ---------------------------------------------------------------------------

def test_build_promotion_suggestions_counts_types():
    claims = [
        {"claim_type": "decision"},
        {"claim_type": "decision"},
        {"claim_type": "action"},
        {"claim_type": "open_loop"},
        {"claim_type": "fact"},
        {"claim_type": "risk"},
        {"claim_type": "insight_candidate"},
    ]
    suggestions = claim_extraction.build_promotion_suggestions(claims)
    by_type = {s["candidate_type"]: s["count"] for s in suggestions}
    assert by_type["adr"] == 2
    assert by_type["daily"] == 2
    assert by_type["card"] == 3


def test_build_promotion_suggestions_empty():
    assert claim_extraction.build_promotion_suggestions([]) == []


def test_build_promotion_suggestions_omits_zero_counts():
    claims = [{"claim_type": "decision"}]
    suggestions = claim_extraction.build_promotion_suggestions(claims)
    candidate_types = {s["candidate_type"] for s in suggestions}
    assert "daily" not in candidate_types
    assert "card" not in candidate_types
    assert "adr" in candidate_types


# ---------------------------------------------------------------------------
# Helpers: seed SQLite fixtures
# ---------------------------------------------------------------------------

def _seed_source_db(tmp_path: Path) -> tuple[Path, str]:
    source_path = tmp_path / "2026-07-04_team_sync.md"
    source_path.write_text(
        "## 摘要\n团队同步会议。\n## 待办\n· 整理 API 文档@张三\n## 决策\n采用 filename_first 归因。\n",
        encoding="utf-8",
    )
    title, chunks, items, metadata = parse_meeting_markdown(source_path)
    content_hash = hash_text_file(source_path)
    db_path = tmp_path / "agent_history.db"
    conn = source_ingest_store.get_db_connection(db_path)
    try:
        source_ingest_store.ingest_document(
            conn, "meeting_note", source_path, title, chunks, items,
            {**metadata, "filename_date": "2026-07-04", "landing_date": "2026-07-04"},
            content_hash,
        )
        conn.commit()
    finally:
        conn.close()
    return db_path, "2026-07-04"


def _seed_chat_db(tmp_path: Path) -> tuple[Path, str]:
    db_path = tmp_path / "agent_history.db"
    conn = source_ingest_store.get_db_connection(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    try:
        conn.execute(
            "INSERT INTO sessions (id, agent_type, project_path, start_time, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("sess_test_001", "antigravity", "/work/projects/data-hub", now, now),
        )
        conn.executemany(
            "INSERT INTO messages (session_id, role, content, timestamp)"
            " VALUES (?, ?, ?, ?)",
            [
                ("sess_test_001", "user", "决定采用 sqlite 作为后端存储。", "2026-07-04T09:01:00"),
                ("sess_test_001", "assistant", "好的，我来帮你实现。", "2026-07-04T09:02:00"),
                ("sess_test_001", "user", "待办：整理 schema 设计文档。", "2026-07-04T09:03:00"),
                # next day — should NOT appear when querying 2026-07-04
                ("sess_test_001", "user", "昨天的问题已经解决了。", "2026-07-05T09:00:00"),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return db_path, "2026-07-04"


# ---------------------------------------------------------------------------
# fetch_source_claims
# ---------------------------------------------------------------------------

def test_fetch_source_claims_returns_claims_for_date(tmp_path):
    db_path, target_date = _seed_source_db(tmp_path)
    conn = source_ingest_store.get_db_connection(db_path)
    try:
        claims, evidence = claim_extraction.fetch_source_claims(conn, target_date)
    finally:
        conn.close()

    assert len(claims) > 0
    assert all(c["source_date"] == target_date for c in claims)
    assert all(c["source_kind"] == "extracted_item" for c in claims)
    assert len(evidence) == len(claims)


def test_fetch_source_claims_empty_for_other_date(tmp_path):
    db_path, _ = _seed_source_db(tmp_path)
    conn = source_ingest_store.get_db_connection(db_path)
    try:
        claims, evidence = claim_extraction.fetch_source_claims(conn, "2026-01-01")
    finally:
        conn.close()
    assert claims == [] and evidence == []


def test_fetch_source_claims_maps_to_valid_claim_types(tmp_path):
    db_path, target_date = _seed_source_db(tmp_path)
    conn = source_ingest_store.get_db_connection(db_path)
    try:
        claims, _ = claim_extraction.fetch_source_claims(conn, target_date)
    finally:
        conn.close()
    valid = {"fact", "decision", "action", "risk", "open_loop", "insight_candidate"}
    assert {c["claim_type"] for c in claims}.issubset(valid)


# ---------------------------------------------------------------------------
# fetch_chat_claims
# ---------------------------------------------------------------------------

def test_fetch_chat_claims_filters_by_date(tmp_path):
    db_path, target_date = _seed_chat_db(tmp_path)
    conn = source_ingest_store.get_db_connection(db_path)
    try:
        claims, evidence = claim_extraction.fetch_chat_claims(conn, target_date)
    finally:
        conn.close()
    # 2 user messages on 2026-07-04 (assistant + 2026-07-05 excluded)
    assert len(claims) == 2
    assert all(c["source_date"] == target_date for c in claims)
    assert all(c["source_kind"] == "chat_message" for c in claims)
    assert len(evidence) == 2


def test_fetch_chat_claims_classifies_correctly(tmp_path):
    db_path, target_date = _seed_chat_db(tmp_path)
    conn = source_ingest_store.get_db_connection(db_path)
    try:
        claims, _ = claim_extraction.fetch_chat_claims(conn, target_date)
    finally:
        conn.close()
    types = {c["claim_type"] for c in claims}
    assert "decision" in types   # "决定采用 sqlite"
    assert "action" in types     # "待办：整理 schema"


# ---------------------------------------------------------------------------
# build_claim_packet — end-to-end
# ---------------------------------------------------------------------------

def test_build_claim_packet_returns_empty_when_no_db(tmp_path, monkeypatch):
    monkeypatch.setattr(claim_extraction, "DB_PATH", tmp_path / "nonexistent.db")
    packet = claim_extraction.build_claim_packet("2026-07-04")
    assert packet["target_date"] == "2026-07-04"
    assert packet["claim_packets"] == []
    assert packet["evidence_links"] == []
    assert packet["promotion_suggestions"] == []


def test_build_claim_packet_skip_chat(tmp_path, monkeypatch):
    db_path, _ = _seed_source_db(tmp_path)
    monkeypatch.setattr(claim_extraction, "DB_PATH", db_path)
    packet = claim_extraction.build_claim_packet("2026-07-04", include_chat=False)
    assert all(c["source_kind"] == "extracted_item" for c in packet["claim_packets"])


def test_build_claim_packet_includes_promotion_suggestions(tmp_path, monkeypatch):
    db_path, _ = _seed_source_db(tmp_path)
    monkeypatch.setattr(claim_extraction, "DB_PATH", db_path)
    packet = claim_extraction.build_claim_packet("2026-07-04", include_chat=False)
    if packet["claim_packets"]:
        assert len(packet["promotion_suggestions"]) > 0
        for s in packet["promotion_suggestions"]:
            assert s["count"] > 0
            assert s["candidate_type"] in {"daily", "adr", "card"}
