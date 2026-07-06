"""Tests for lifecycle stage 7 — hygiene_audit.py."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

DATA_HUB_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import hygiene_audit
import source_ingest_store
from source_adapters.common import Chunk, Item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(tmp_path: Path):
    db_path = tmp_path / "agent_history.db"
    return source_ingest_store.get_db_connection(db_path), db_path


def _seed_document_and_item(conn, tmp_path, filename="2026-07-04_meeting.md",
                             filename_date="2026-07-04", landing_date="2026-07-04",
                             item_type="action", suffix=""):
    """Return (doc_id, item_id) for a freshly inserted document+item pair."""
    tag = suffix or filename_date
    source_path = tmp_path / f"{tag}_{filename}"
    source_path.write_text(f"摘要\n· 任务_{tag}@张三\n", encoding="utf-8")
    doc_id = source_ingest_store.upsert_document(
        conn, "meeting_note", source_path, f"会议_{tag}", f"hash_{tag}",
        {"filename_date": filename_date, "landing_date": landing_date},
    )
    chunk_ids = source_ingest_store.insert_chunks(
        conn, doc_id,
        [Chunk(chunk_type="paragraph", locator="p1", content=f"任务_{tag}", metadata={})],
    )
    source_ingest_store.insert_items(
        conn, doc_id, chunk_ids,
        [Item(item_type=item_type, title=f"任务_{tag}", content=f"任务_{tag}",
              confidence=0.85, chunk_index=0, metadata={})],
    )
    item_id = conn.execute(
        "SELECT id FROM extracted_items WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]
    conn.commit()
    return doc_id, item_id


def _insert_candidate(conn, cand_id, extracted_item_id, source_document_id,
                       status="pending", candidate_type="daily",
                       candidate_date="2026-07-04", title="Test",
                       materialized_path=None):
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO knowledge_candidates
           (id, extracted_item_id, source_document_id, candidate_date, candidate_type,
            status, title, content, confidence, metadata_json, created_at, updated_at,
            materialized_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cand_id, extracted_item_id, source_document_id, candidate_date,
         candidate_type, status, title, "content", 0.8, "{}", now, now, materialized_path),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# fetch_orphan_candidates
# ---------------------------------------------------------------------------

def test_fetch_orphan_candidates_empty_when_healthy(tmp_path):
    conn, _ = _make_conn(tmp_path)
    doc_id, item_id = _seed_document_and_item(conn, tmp_path)
    _insert_candidate(conn, "cand_healthy", item_id, doc_id)
    orphans = hygiene_audit.fetch_orphan_candidates(conn)
    conn.close()
    assert orphans == []


def test_fetch_orphan_candidates_detects_deleted_source_document(tmp_path):
    conn, _ = _make_conn(tmp_path)
    doc_id, item_id = _seed_document_and_item(conn, tmp_path, suffix="del_doc")
    _insert_candidate(conn, "cand_del_doc", item_id, doc_id)

    # Delete source document; cascade deletes extracted_item too, leaving orphaned candidate
    # We have to bypass cascade: delete candidate FK ref manually first then restore
    # Simpler: disable FK, delete doc, re-enable
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM source_documents WHERE id = ?", (doc_id,))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()

    orphans = hygiene_audit.fetch_orphan_candidates(conn)
    conn.close()
    assert any(o["id"] == "cand_del_doc" for o in orphans)


def test_fetch_orphan_candidates_detects_deleted_extracted_item(tmp_path):
    conn, _ = _make_conn(tmp_path)
    doc_id, item_id = _seed_document_and_item(conn, tmp_path, suffix="del_item")
    _insert_candidate(conn, "cand_del_item", item_id, doc_id)

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM extracted_items WHERE id = ?", (item_id,))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()

    orphans = hygiene_audit.fetch_orphan_candidates(conn)
    conn.close()
    assert any(o["id"] == "cand_del_item" for o in orphans)


# ---------------------------------------------------------------------------
# fetch_stale_review_items
# ---------------------------------------------------------------------------

def test_fetch_stale_review_items_empty_when_recent(tmp_path):
    conn, _ = _make_conn(tmp_path)
    doc_id, item_id = _seed_document_and_item(conn, tmp_path)
    _insert_candidate(conn, "cand_recent", item_id, doc_id,
                       candidate_date="2026-07-04")
    # stale_before == candidate_date → not stale (strict less-than)
    stale = hygiene_audit.fetch_stale_review_items(conn, "2026-07-04")
    conn.close()
    assert stale == []


def test_fetch_stale_review_items_detects_old_pending(tmp_path):
    conn, _ = _make_conn(tmp_path)
    doc_id, item_id = _seed_document_and_item(
        conn, tmp_path, filename_date="2026-05-01", landing_date="2026-05-01", suffix="old"
    )
    _insert_candidate(conn, "cand_old_pending", item_id, doc_id,
                       status="pending", candidate_date="2026-05-01")
    stale = hygiene_audit.fetch_stale_review_items(conn, "2026-07-01")
    conn.close()
    assert any(s["id"] == "cand_old_pending" for s in stale)


def test_fetch_stale_review_items_skips_accepted(tmp_path):
    conn, _ = _make_conn(tmp_path)
    doc_id, item_id = _seed_document_and_item(
        conn, tmp_path, filename_date="2026-05-01", landing_date="2026-05-01", suffix="acc"
    )
    _insert_candidate(conn, "cand_accepted_old", item_id, doc_id,
                       status="accepted", candidate_date="2026-05-01")
    stale = hygiene_audit.fetch_stale_review_items(conn, "2026-07-01")
    conn.close()
    assert not any(s["id"] == "cand_accepted_old" for s in stale)


# ---------------------------------------------------------------------------
# fetch_duplicate_knowledge_candidates
# ---------------------------------------------------------------------------

def test_fetch_duplicate_candidates_empty_when_unique(tmp_path):
    conn, _ = _make_conn(tmp_path)
    doc_id, item_id = _seed_document_and_item(conn, tmp_path, suffix="uniq")
    _insert_candidate(conn, "cand_adr_uniq", item_id, doc_id,
                       status="accepted", candidate_type="adr", title="采用 filename_first")
    dups = hygiene_audit.fetch_duplicate_knowledge_candidates(conn)
    conn.close()
    assert dups == []


def test_fetch_duplicate_candidates_detects_same_title(tmp_path):
    conn, _ = _make_conn(tmp_path)
    # Need two separate items (UNIQUE constraint on extracted_item_id)
    doc_id1, item_id1 = _seed_document_and_item(conn, tmp_path, suffix="dup1")
    doc_id2, item_id2 = _seed_document_and_item(conn, tmp_path, suffix="dup2")
    _insert_candidate(conn, "cand_dup_1", item_id1, doc_id1,
                       status="accepted", candidate_type="adr", title="采用 filename_first")
    _insert_candidate(conn, "cand_dup_2", item_id2, doc_id2,
                       status="accepted", candidate_type="adr", title="采用 filename_first")
    dups = hygiene_audit.fetch_duplicate_knowledge_candidates(conn)
    conn.close()
    assert len(dups) >= 1
    assert dups[0]["duplicate_count"] >= 2


# ---------------------------------------------------------------------------
# fetch_date_anomalies
# ---------------------------------------------------------------------------

def test_fetch_date_anomalies_empty_when_dates_match(tmp_path):
    conn, _ = _make_conn(tmp_path)
    _seed_document_and_item(conn, tmp_path,
                            filename_date="2026-07-04", landing_date="2026-07-04")
    anomalies = hygiene_audit.fetch_date_anomalies(conn)
    conn.close()
    assert anomalies == []


def test_fetch_date_anomalies_detects_mismatch(tmp_path):
    conn, _ = _make_conn(tmp_path)
    _seed_document_and_item(conn, tmp_path,
                            filename_date="2026-05-01", landing_date="2026-07-04",
                            suffix="anomaly")
    anomalies = hygiene_audit.fetch_date_anomalies(conn)
    conn.close()
    assert len(anomalies) == 1
    assert anomalies[0]["filename_date"] == "2026-05-01"
    assert anomalies[0]["landing_date"] == "2026-07-04"


# ---------------------------------------------------------------------------
# fetch_broken_materializations
# ---------------------------------------------------------------------------

def test_fetch_broken_materializations_empty_when_healthy(tmp_path, monkeypatch):
    conn, _ = _make_conn(tmp_path)
    vault = tmp_path / "vault"
    note = vault / "40_Knowledge" / "Cards" / "2026-07-04-test.md"
    note.parent.mkdir(parents=True)

    doc_id, item_id = _seed_document_and_item(conn, tmp_path, suffix="good_mat")
    cand_id = "cand_good_mat"
    note.write_text(f"# Test\ncandidate_id: {cand_id}\n", encoding="utf-8")
    _insert_candidate(conn, cand_id, item_id, doc_id, status="accepted",
                       candidate_type="card",
                       materialized_path="40_Knowledge/Cards/2026-07-04-test.md")

    monkeypatch.setattr(hygiene_audit, "OBSIDIAN_VAULT_DIR", vault)
    broken = hygiene_audit.fetch_broken_materializations(conn)
    conn.close()
    assert broken == []


def test_fetch_broken_materializations_detects_missing_file(tmp_path, monkeypatch):
    conn, _ = _make_conn(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    doc_id, item_id = _seed_document_and_item(conn, tmp_path, suffix="no_file")
    _insert_candidate(conn, "cand_no_file", item_id, doc_id, status="accepted",
                       candidate_type="adr",
                       materialized_path="40_Knowledge/ADR/nonexistent.md")

    monkeypatch.setattr(hygiene_audit, "OBSIDIAN_VAULT_DIR", vault)
    broken = hygiene_audit.fetch_broken_materializations(conn)
    conn.close()
    assert any(b["problem"] == "missing_file" for b in broken)


def test_fetch_broken_materializations_detects_missing_marker(tmp_path, monkeypatch):
    conn, _ = _make_conn(tmp_path)
    vault = tmp_path / "vault"
    note = vault / "40_Knowledge" / "Cards" / "2026-07-04-nomarker.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Test\n没有 candidate_id marker\n", encoding="utf-8")

    doc_id, item_id = _seed_document_and_item(conn, tmp_path, suffix="no_marker")
    _insert_candidate(conn, "cand_no_marker", item_id, doc_id, status="accepted",
                       candidate_type="card",
                       materialized_path="40_Knowledge/Cards/2026-07-04-nomarker.md")

    monkeypatch.setattr(hygiene_audit, "OBSIDIAN_VAULT_DIR", vault)
    broken = hygiene_audit.fetch_broken_materializations(conn)
    conn.close()
    assert any(b["problem"] == "missing_candidate_marker" for b in broken)


# ---------------------------------------------------------------------------
# build_audit_report
# ---------------------------------------------------------------------------

def test_build_audit_report_returns_fallback_when_no_db(tmp_path, monkeypatch):
    monkeypatch.setattr(hygiene_audit, "DB_PATH", tmp_path / "nonexistent.db")
    report = hygiene_audit.build_audit_report("2026-07-01")
    assert report["orphan_candidates"] == []
    assert "SQLite ledger not found" in report["repair_recommendations"][0]


def test_build_audit_report_healthy_db_has_no_issues(tmp_path, monkeypatch):
    conn, db_path = _make_conn(tmp_path)
    vault = tmp_path / "vault"
    note = vault / "10_Periodic" / "Daily" / "2026-07-04.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Daily\ncandidate_id: cand_healthy_report\n", encoding="utf-8")

    doc_id, item_id = _seed_document_and_item(conn, tmp_path,
                                               filename_date="2026-07-04",
                                               landing_date="2026-07-04",
                                               suffix="healthy_report")
    _insert_candidate(conn, "cand_healthy_report", item_id, doc_id,
                       status="accepted", candidate_type="daily",
                       candidate_date="2026-07-04",
                       materialized_path="10_Periodic/Daily/2026-07-04.md")
    conn.close()

    monkeypatch.setattr(hygiene_audit, "DB_PATH", db_path)
    monkeypatch.setattr(hygiene_audit, "OBSIDIAN_VAULT_DIR", vault)

    report = hygiene_audit.build_audit_report("2099-01-01")

    assert report["orphan_candidates"] == []
    assert report["stale_review_items"] == []
    assert report["duplicate_knowledge_candidates"] == []
    assert report["date_anomalies"] == []
    assert report["broken_materializations"] == []
    assert "No hygiene issues" in report["repair_recommendations"][0]
