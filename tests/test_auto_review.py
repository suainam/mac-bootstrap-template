"""Tests for lifecycle stage 4 (auto_review) — auto_review.py."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(SCRIPTS_DIR))

import auto_review
import source_ingest_store
from source_adapters.common import Chunk, Item


# ---------------------------------------------------------------------------
# Fixture helpers: seed a real document+item+candidate chain
# ---------------------------------------------------------------------------

def _make_conn(tmp_path: Path):
    db_path = tmp_path / "agent_history.db"
    return source_ingest_store.get_db_connection(db_path)


def _seed_candidate(conn, tmp_path, candidate_type="daily", confidence=0.85,
                    status="pending", candidate_date="2026-07-04", suffix=""):
    """Seed one complete document → extracted_item → candidate chain."""
    tag = f"{candidate_type}_{suffix or str(confidence).replace('.', '')}"
    source_path = tmp_path / f"2026-07-04_{tag}.md"
    source_path.write_text(f"摘要\n待办\n· 任务_{tag}@张三\n", encoding="utf-8")
    doc_id = source_ingest_store.upsert_document(
        conn, "meeting_note", source_path, f"会议_{tag}", f"hash_{tag}",
        {"filename_date": candidate_date, "landing_date": candidate_date},
    )
    chunk_ids = source_ingest_store.insert_chunks(
        conn, doc_id,
        [Chunk(chunk_type="paragraph", locator="p1", content=f"任务_{tag}", metadata={})],
    )
    source_ingest_store.insert_items(
        conn, doc_id, chunk_ids,
        [Item(item_type="action", title=f"任务_{tag}", content=f"任务_{tag}",
              confidence=confidence, chunk_index=0, metadata={})],
    )
    item_id = conn.execute(
        "SELECT id FROM extracted_items WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]

    now = datetime.now().isoformat(timespec="seconds")
    cand_id = f"cand_{tag}"
    conn.execute(
        """INSERT INTO knowledge_candidates
           (id, extracted_item_id, source_document_id, candidate_date, candidate_type,
            status, title, content, confidence, metadata_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cand_id, item_id, doc_id, candidate_date, candidate_type,
         status, f"Title_{tag}", f"Content_{tag}", confidence, "{}", now, now),
    )
    conn.commit()
    return cand_id


# ---------------------------------------------------------------------------
# Threshold boundary tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("candidate_type,threshold", [
    ("daily", 0.8),
    ("card",  0.8),
    ("adr",   0.85),
])
def test_auto_review_accepts_at_or_above_threshold(tmp_path, candidate_type, threshold):
    conn = _make_conn(tmp_path)
    cand_id = _seed_candidate(conn, tmp_path, candidate_type=candidate_type,
                               confidence=threshold)

    from execution_logger import ExecutionLogger
    logger = ExecutionLogger(conn, "2026-07-04")
    stats = auto_review.auto_review_candidates(conn, "2026-07-04", logger)

    status = conn.execute(
        "SELECT status FROM knowledge_candidates WHERE id = ?", (cand_id,)
    ).fetchone()[0]
    conn.close()

    assert status == "accepted"
    assert stats["accepted"] >= 1


@pytest.mark.parametrize("candidate_type,below_threshold", [
    ("daily", 0.79),
    ("card",  0.79),
    ("adr",   0.84),
])
def test_auto_review_keeps_pending_below_threshold(tmp_path, candidate_type, below_threshold):
    conn = _make_conn(tmp_path)
    cand_id = _seed_candidate(conn, tmp_path, candidate_type=candidate_type,
                               confidence=below_threshold)

    from execution_logger import ExecutionLogger
    logger = ExecutionLogger(conn, "2026-07-04")
    auto_review.auto_review_candidates(conn, "2026-07-04", logger)

    status = conn.execute(
        "SELECT status FROM knowledge_candidates WHERE id = ?", (cand_id,)
    ).fetchone()[0]
    conn.close()

    assert status == "pending"


def test_auto_review_unknown_type_uses_strict_threshold(tmp_path):
    """Unknown candidate_type should fall back to 0.9 threshold."""
    conn = _make_conn(tmp_path)
    low_id  = _seed_candidate(conn, tmp_path, candidate_type="unknown_type",
                               confidence=0.89, suffix="low")
    high_id = _seed_candidate(conn, tmp_path, candidate_type="unknown_type",
                               confidence=0.91, suffix="high")

    from execution_logger import ExecutionLogger
    logger = ExecutionLogger(conn, "2026-07-04")
    auto_review.auto_review_candidates(conn, "2026-07-04", logger)

    low_status  = conn.execute("SELECT status FROM knowledge_candidates WHERE id = ?",
                                (low_id,)).fetchone()[0]
    high_status = conn.execute("SELECT status FROM knowledge_candidates WHERE id = ?",
                                (high_id,)).fetchone()[0]
    conn.close()

    assert low_status  == "pending"
    assert high_status == "accepted"


# ---------------------------------------------------------------------------
# Status preservation
# ---------------------------------------------------------------------------

def test_auto_review_does_not_touch_already_accepted(tmp_path):
    conn = _make_conn(tmp_path)
    # Already accepted with LOW confidence — should NOT become pending
    cand_id = _seed_candidate(conn, tmp_path, confidence=0.5, status="accepted")

    from execution_logger import ExecutionLogger
    logger = ExecutionLogger(conn, "2026-07-04")
    stats = auto_review.auto_review_candidates(conn, "2026-07-04", logger)

    status = conn.execute(
        "SELECT status FROM knowledge_candidates WHERE id = ?", (cand_id,)
    ).fetchone()[0]
    conn.close()

    assert status == "accepted"
    assert stats["accepted"] == 0  # nothing newly accepted


def test_auto_review_does_not_touch_rejected(tmp_path):
    conn = _make_conn(tmp_path)
    cand_id = _seed_candidate(conn, tmp_path, confidence=0.95, status="rejected")

    from execution_logger import ExecutionLogger
    logger = ExecutionLogger(conn, "2026-07-04")
    stats = auto_review.auto_review_candidates(conn, "2026-07-04", logger)

    status = conn.execute(
        "SELECT status FROM knowledge_candidates WHERE id = ?", (cand_id,)
    ).fetchone()[0]
    conn.close()

    assert status == "rejected"
    assert stats["accepted"] == 0


# ---------------------------------------------------------------------------
# Mixed batch
# ---------------------------------------------------------------------------

def test_auto_review_mixed_batch_returns_correct_counts(tmp_path):
    conn = _make_conn(tmp_path)
    _seed_candidate(conn, tmp_path, candidate_type="daily", confidence=0.90, suffix="a1")
    _seed_candidate(conn, tmp_path, candidate_type="adr",   confidence=0.90, suffix="a2")
    _seed_candidate(conn, tmp_path, candidate_type="daily", confidence=0.75, suffix="p1")
    _seed_candidate(conn, tmp_path, candidate_type="card",  confidence=0.70, suffix="p2")

    from execution_logger import ExecutionLogger
    logger = ExecutionLogger(conn, "2026-07-04")
    stats = auto_review.auto_review_candidates(conn, "2026-07-04", logger)
    conn.close()

    assert stats["accepted"] == 2
    assert stats["pending"]  == 2


# ---------------------------------------------------------------------------
# Empty candidates
# ---------------------------------------------------------------------------

def test_auto_review_empty_candidates(tmp_path):
    conn = _make_conn(tmp_path)
    from execution_logger import ExecutionLogger
    logger = ExecutionLogger(conn, "2026-07-04")
    stats = auto_review.auto_review_candidates(conn, "2026-07-04", logger)
    conn.close()

    assert stats == {"accepted": 0, "pending": 0, "skipped": 0}


# ---------------------------------------------------------------------------
# Date isolation
# ---------------------------------------------------------------------------

def test_auto_review_only_processes_target_date(tmp_path):
    conn = _make_conn(tmp_path)
    # Seed candidate for a different date — should NOT be touched
    other_id = _seed_candidate(conn, tmp_path, confidence=0.95,
                                candidate_date="2026-07-03", suffix="other")

    from execution_logger import ExecutionLogger
    logger = ExecutionLogger(conn, "2026-07-04")
    stats = auto_review.auto_review_candidates(conn, "2026-07-04", logger)

    status = conn.execute(
        "SELECT status FROM knowledge_candidates WHERE id = ?", (other_id,)
    ).fetchone()[0]
    conn.close()

    assert status == "pending"   # untouched
    assert stats["accepted"] == 0


def test_auto_review_skips_chat_candidates(tmp_path):
    conn = _make_conn(tmp_path)
    cand_id = _seed_candidate(conn, tmp_path, candidate_type="adr", confidence=0.95, suffix="chat")
    conn.execute(
        "UPDATE knowledge_candidates SET metadata_json = ? WHERE id = ?",
        ('{"source_kind":"chat_message","message_id":1}', cand_id),
    )
    conn.commit()

    from execution_logger import ExecutionLogger
    logger = ExecutionLogger(conn, "2026-07-04")
    stats = auto_review.auto_review_candidates(conn, "2026-07-04", logger)

    status = conn.execute(
        "SELECT status FROM knowledge_candidates WHERE id = ?", (cand_id,)
    ).fetchone()[0]
    conn.close()

    assert status == "pending"
    assert stats == {"accepted": 0, "pending": 0, "skipped": 1}


def test_auto_review_main_prints_skipped_count(monkeypatch, capsys):
    monkeypatch.setattr(auto_review, "load_env", lambda: None)
    monkeypatch.setattr(auto_review, "get_db_connection", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(auto_review.ExecutionLogger, "start", lambda self, step_name: "log-1")
    monkeypatch.setattr(auto_review.ExecutionLogger, "complete", lambda self, log_id, records_affected, metadata=None: None)
    monkeypatch.setattr(
        auto_review,
        "auto_review_candidates",
        lambda conn, target_date, logger: {"accepted": 1, "pending": 2, "skipped": 3},
    )
    monkeypatch.setattr(sys, "argv", ["auto_review.py", "2026-07-04"])

    auto_review.main()

    assert "[auto_review] 2026-07-04: accepted=1, pending=2, skipped=3" in capsys.readouterr().out
