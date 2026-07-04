from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(SCRIPTS_DIR))

import auto_review
import generate_candidates
import ingest_sources
from data_hub_test_support import seed_message_and_source_data, temp_db_and_vault
from db_helper import (
    get_db_connection,
    query_candidates_by_date,
    query_candidates_count,
    query_execution_log,
    query_messages_count,
    query_sessions_count,
    query_source_documents_count,
)
from source_adapters import iter_source_files, parse_source


def test_ingest_sources_and_generate_candidates_main(temp_db_and_vault, monkeypatch) -> None:
    _db_path, vault_dir = temp_db_and_vault
    meeting_path = vault_dir / "50_Sources" / "Meetings" / "2026-07-10_weekly-sync.md"
    meeting_path.write_text("决策\n采用轻量审核\n待办\n- 跟进门店实验\n", encoding="utf-8")

    monkeypatch.setattr(ingest_sources, "OBSIDIAN_VAULT_DIR", vault_dir)
    monkeypatch.setattr(sys, "argv", ["ingest_sources.py"])
    ingest_sources.main()

    conn = get_db_connection()
    try:
        assert query_source_documents_count(conn) == 1
    finally:
        conn.close()

    monkeypatch.setattr(sys, "argv", ["generate_candidates.py", "2026-07-10"])
    monkeypatch.setattr(generate_candidates, "CANDIDATE_DIR", vault_dir / "60_Inbox" / "Candidates")
    generate_candidates.main()

    review_path = vault_dir / "60_Inbox" / "Candidates" / "2026-07-10.md"
    assert review_path.exists()
    rendered = review_path.read_text(encoding="utf-8")
    assert "Candidate Review 2026-07-10" in rendered

    conn = get_db_connection()
    try:
        rows = query_candidates_by_date(conn, "2026-07-10")
        candidate_logs = query_execution_log(conn, "2026-07-10")
        ingest_logs_today = query_execution_log(conn, datetime.now().strftime("%Y-%m-%d"))
    finally:
        conn.close()

    assert rows
    assert any(log["step_name"] == "ingest_sources" for log in ingest_logs_today)
    assert any(log["step_name"] == "generate_candidates" for log in candidate_logs)


def test_db_helpers_source_adapters_and_auto_review_fallback(temp_db_and_vault) -> None:
    db_path, vault_dir = temp_db_and_vault
    seed_message_and_source_data(db_path, vault_dir)

    wiki_path = vault_dir / "50_Sources" / "Wiki-Clips" / "2026-07-11_retro.md"
    wiki_path.write_text("# 复盘\n- 风险项\n普通事实\n", encoding="utf-8")
    files = list(iter_source_files(vault_dir))
    assert ("wiki_page", wiki_path) in files

    title, chunks, items, metadata, content_hash = parse_source("wiki_page", wiki_path)
    assert title == "复盘"
    assert metadata["source_kind"] == "wiki_page"
    assert content_hash
    assert {chunk.chunk_type for chunk in chunks} == {"heading", "bullet"}
    assert len(items) == 2

    conn = get_db_connection()
    try:
        now = datetime.now().isoformat(timespec="seconds")
        extracted_item_id = conn.execute(
            "SELECT id FROM extracted_items ORDER BY rowid LIMIT 1 OFFSET 1"
        ).fetchone()[0]
        source_document_id = conn.execute(
            "SELECT id FROM source_documents ORDER BY rowid LIMIT 1"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO knowledge_candidates
                (id, extracted_item_id, source_document_id, candidate_date, candidate_type, status,
                 title, content, confidence, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cand-unknown",
                extracted_item_id,
                source_document_id,
                "2026-07-11",
                "unknown",
                "pending",
                "未知候选",
                "需要默认阈值",
                0.95,
                "{}",
                now,
                now,
            ),
        )
        conn.commit()

        stats = auto_review.auto_review_candidates(conn, "2026-07-11", logger=None)
        status = conn.execute(
            "SELECT status FROM knowledge_candidates WHERE id = ?",
            ("cand-unknown",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert stats["accepted"] == 1
    assert status == "accepted"

    conn = get_db_connection()
    try:
        assert query_candidates_count(conn) >= 2
        assert query_sessions_count(conn) == 1
        assert query_messages_count(conn) == 2
        pending_rows = query_candidates_by_date(conn, "2026-07-08", status="pending")
    finally:
        conn.close()
    assert pending_rows
