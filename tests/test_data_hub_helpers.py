"""Tests for data-hub common helpers."""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path

import pytest

from helpers import DATA_HUB


@pytest.fixture
def temp_db():
    """Create temporary test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Minimal schema for testing
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS execution_log (
            id TEXT PRIMARY KEY,
            execution_date TEXT NOT NULL,
            step_name TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
            records_affected INTEGER,
            error_message TEXT,
            metadata_json TEXT,
            UNIQUE(execution_date, step_name, started_at)
        );

        CREATE TABLE IF NOT EXISTS knowledge_candidates (
            id TEXT PRIMARY KEY,
            candidate_date TEXT NOT NULL,
            candidate_type TEXT NOT NULL,
            status TEXT NOT NULL,
            confidence REAL NOT NULL
        );
    """)
    conn.commit()

    yield conn

    conn.close()
    db_path.unlink()


def test_execution_logger_lifecycle(temp_db):
    """Test ExecutionLogger start/complete/fail workflow."""
    import sys
    sys.path.insert(0, str(DATA_HUB))
    sys.path.insert(0, str(DATA_HUB / "scripts"))
    from execution_logger import ExecutionLogger

    logger = ExecutionLogger(temp_db, "2026-07-04")

    # Start step
    log_id = logger.start("test_step")
    assert log_id.startswith("log_")

    # Check running status
    logs = logger.get_today_logs()
    assert len(logs) == 1
    assert logs[0]["status"] == "running"
    assert logs[0]["step_name"] == "test_step"

    # Complete step
    logger.complete(log_id, records_affected=10, metadata={"test": "value"})

    logs = logger.get_today_logs()
    assert logs[0]["status"] == "completed"
    assert logs[0]["records_affected"] == 10
    assert "test" in logs[0]["metadata_json"]


def test_execution_logger_fail(temp_db):
    """Test ExecutionLogger failure handling."""
    import sys
    sys.path.insert(0, str(DATA_HUB))
    sys.path.insert(0, str(DATA_HUB / "scripts"))
    from execution_logger import ExecutionLogger

    logger = ExecutionLogger(temp_db, "2026-07-04")
    log_id = logger.start("failing_step")

    logger.fail(log_id, "Test error message")

    logs = logger.get_today_logs()
    assert logs[0]["status"] == "failed"
    assert logs[0]["error_message"] == "Test error message"


def test_date_utils_workday():
    """Test workday detection."""
    import sys
    sys.path.insert(0, str(DATA_HUB))
    sys.path.insert(0, str(DATA_HUB / "scripts"))
    from date_utils import is_workday, get_week_range, get_year_week

    # Test with known dates (2026-07-06 is Monday)
    monday = date(2026, 7, 6)
    assert is_workday(monday) is True

    # Test with date string
    assert is_workday("2026-07-06") is True

    # Test week range
    start, end = get_week_range(monday)
    assert start == monday
    assert (end - start).days == 6

    # Test year-week format
    year_week = get_year_week(monday)
    assert year_week == "2026-W28"


def test_auto_review_thresholds(temp_db):
    """Test auto_review accepts candidates above threshold."""
    import sys
    sys.path.insert(0, str(DATA_HUB))
    sys.path.insert(0, str(DATA_HUB / "scripts"))
    from auto_review import auto_review_candidates
    from execution_logger import ExecutionLogger

    # Insert test candidates
    temp_db.execute(
        "INSERT INTO knowledge_candidates (id, candidate_date, candidate_type, status, confidence) VALUES (?, ?, ?, ?, ?)",
        ("cand_1", "2026-07-04", "card", "pending", 0.85)
    )
    temp_db.execute(
        "INSERT INTO knowledge_candidates (id, candidate_date, candidate_type, status, confidence) VALUES (?, ?, ?, ?, ?)",
        ("cand_2", "2026-07-04", "card", "pending", 0.75)
    )
    temp_db.execute(
        "INSERT INTO knowledge_candidates (id, candidate_date, candidate_type, status, confidence) VALUES (?, ?, ?, ?, ?)",
        ("cand_3", "2026-07-04", "adr", "pending", 0.86)
    )
    temp_db.commit()

    logger = ExecutionLogger(temp_db, "2026-07-04")
    stats = auto_review_candidates(temp_db, "2026-07-04", logger)

    # card threshold 0.8: cand_1 (0.85) accepted, cand_2 (0.75) pending
    # adr threshold 0.85: cand_3 (0.86) accepted
    assert stats["accepted"] == 2
    assert stats["pending"] == 1

    # Verify status updates
    row1 = temp_db.execute("SELECT status FROM knowledge_candidates WHERE id = 'cand_1'").fetchone()
    assert row1["status"] == "accepted"

    row2 = temp_db.execute("SELECT status FROM knowledge_candidates WHERE id = 'cand_2'").fetchone()
    assert row2["status"] == "pending"
