import sys
from datetime import datetime
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(SCRIPTS_DIR))

import materialize_candidates
import source_ingest_store
from candidate_review_io import ReviewItem
from source_adapters.common import Chunk, Item


def seed_document_with_candidate(tmp_path: Path):
    db_path = tmp_path / "agent_history.db"
    conn = source_ingest_store.get_db_connection(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    try:
        source_path = tmp_path / "2026-07-04_review.md"
        source_path.write_text("决定采用 filename_first。", encoding="utf-8")
        doc_id = source_ingest_store.upsert_document(
            conn,
            "wiki_page",
            source_path,
            "知识库方案",
            "hash-demo",
            {"filename_date": "2026-07-04", "landing_date": "2026-07-04"},
        )
        chunk_ids = source_ingest_store.insert_chunks(
            conn,
            doc_id,
            [Chunk(chunk_type="paragraph", locator="p1", content="决定采用 filename_first。", metadata={})],
        )
        source_ingest_store.insert_items(
            conn,
            doc_id,
            chunk_ids,
            [Item(item_type="decision", title="采用 filename_first", content="默认按文件名日期归因。", confidence=0.92, chunk_index=0, metadata={})],
        )
        extracted_item_id = conn.execute(
            "SELECT id FROM extracted_items WHERE document_id = ?",
            (doc_id,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO knowledge_candidates
                (id, extracted_item_id, source_document_id, candidate_date, candidate_type, status,
                 title, content, confidence, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cand_demo_adr",
                extracted_item_id,
                doc_id,
                "2026-07-04",
                "adr",
                "pending",
                "采用 filename_first",
                "默认按文件名日期归因。",
                0.92,
                '{"source_type":"wiki_page","document_title":"知识库方案"}',
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_materialize_note_candidate_is_idempotent(tmp_path: Path):
    note_path = tmp_path / "40_Knowledge" / "Cards" / "2026-07-04-card.md"

    materialize_candidates.materialize_note_candidate(
        note_path,
        "card",
        "2026-07-04",
        "线下实验不能只看销售额",
        "至少同时看销售额和替代率。",
        "meeting_note / 周会",
        "cand_card_demo",
    )
    materialize_candidates.materialize_note_candidate(
        note_path,
        "card",
        "2026-07-04",
        "线下实验不能只看销售额",
        "至少同时看销售额和替代率。",
        "meeting_note / 周会",
        "cand_card_demo",
    )

    text = note_path.read_text(encoding="utf-8")
    assert text.count("candidate_id: cand_card_demo") == 1
    assert text.count("# 线下实验不能只看销售额") == 1


def test_apply_review_actions_updates_status_and_materialized_path(tmp_path: Path, monkeypatch):
    db_path = seed_document_with_candidate(tmp_path)
    vault_dir = tmp_path / "vault"
    monkeypatch.setattr(materialize_candidates, "OBSIDIAN_VAULT_DIR", vault_dir)

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        changed, materialized = materialize_candidates.apply_review_actions(
            conn,
            "2026-07-04",
            [ReviewItem(candidate_id="cand_demo_adr", title="采用 filename_first", review_action="accept", review_note="进入 ADR")],
        )
        row = conn.execute(
            "SELECT status, materialized_path, review_note FROM knowledge_candidates WHERE id = ?",
            ("cand_demo_adr",),
        ).fetchone()
    finally:
        conn.close()

    assert changed == 1
    assert materialized == 1
    assert row["status"] == "accepted"
    assert row["review_note"] == "进入 ADR"
    assert row["materialized_path"].startswith("40_Knowledge/ADR/")

    note_path = vault_dir / row["materialized_path"]
    assert note_path.exists()
    assert "candidate_id: cand_demo_adr" in note_path.read_text(encoding="utf-8")
