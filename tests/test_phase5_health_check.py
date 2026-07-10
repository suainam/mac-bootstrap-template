"""Tests for Phase 5 - health_check.py."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from helpers import DATA_HUB

# Add data-hub to sys.path
sys.path.insert(0, str(DATA_HUB))
sys.path.insert(0, str(DATA_HUB / "scripts"))

from health_check import format_report, get_failed_executions


@pytest.fixture
def temp_db_with_logs():
    """Create temporary DB with execution_log data spanning multiple days."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Schema for execution_log
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
    """)

    # Insert test data: 3 days of logs (2 failed, 3 completed)
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    four_days_ago = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d")

    test_logs = [
        # Recent failures (within 3 days)
        ("log_1", today, "ingest_logs", "2026-07-04T08:00:00", "2026-07-04T08:05:00", "failed", None, "Database locked"),
        ("log_2", yesterday, "daily_summary", "2026-07-03T18:00:00", "2026-07-03T18:02:00", "failed", None, "LLM timeout"),
        # Recent successes
        ("log_3", today, "ingest_sources", "2026-07-04T09:00:00", "2026-07-04T09:01:00", "completed", 15, None),
        ("log_4", two_days_ago, "generate_candidates", "2026-07-02T10:00:00", "2026-07-02T10:03:00", "completed", 8, None),
        # Old failure (outside 3-day window)
        ("log_5", four_days_ago, "health_check", "2026-06-30T18:00:00", "2026-06-30T18:01:00", "failed", None, "Script error"),
    ]

    conn.executemany(
        "INSERT INTO execution_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(log[0], log[1], log[2], log[3], log[4], log[5], log[6], log[7], None) for log in test_logs]
    )
    conn.commit()

    yield conn, db_path

    conn.close()
    db_path.unlink()


def test_format_report_no_failures():
    """Test format_report with empty failed logs."""
    report = format_report([])
    assert "✅ All pipeline steps succeeded" in report
    assert "3 days" in report


def test_format_report_with_failures():
    """Test format_report with failed logs."""
    failed_logs = [
        {
            "execution_date": "2026-07-04",
            "step_name": "ingest_logs",
            "started_at": "2026-07-04T08:00:00",
            "completed_at": "2026-07-04T08:05:00",
            "error_message": "Database locked",
        },
        {
            "execution_date": "2026-07-03",
            "step_name": "daily_summary",
            "started_at": "2026-07-03T18:00:00",
            "completed_at": "2026-07-03T18:02:00",
            "error_message": "LLM timeout",
        },
    ]

    report = format_report(failed_logs)
    assert "⚠️" in report
    assert "Pipeline Health Check Report" in report
    assert "Failed steps in the last 3 days: 2" in report
    assert "ingest_logs" in report
    assert "Database locked" in report
    assert "daily_summary" in report
    assert "LLM timeout" in report


def test_get_failed_executions_filters_by_date(temp_db_with_logs, monkeypatch):
    """Test get_failed_executions returns only recent failed logs."""
    conn, db_path = temp_db_with_logs

    # Mock AGENT_DB_PATH to use our temp DB
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))

    failed = get_failed_executions(days=3)

    # Should return only 2 failures within 3 days (not the 4-day-old one)
    assert len(failed) == 2
    step_names = {log["step_name"] for log in failed}
    assert "ingest_logs" in step_names
    assert "daily_summary" in step_names
    assert "health_check" not in step_names  # 4 days old, excluded


def test_get_failed_executions_excludes_completed(temp_db_with_logs, monkeypatch):
    """Test get_failed_executions excludes completed logs."""
    conn, db_path = temp_db_with_logs

    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))

    failed = get_failed_executions(days=3)

    # Should not include completed steps
    step_names = {log["step_name"] for log in failed}
    assert "ingest_sources" not in step_names  # completed, excluded
    assert "generate_candidates" not in step_names  # completed, excluded


def test_get_failed_executions_default_days(temp_db_with_logs, monkeypatch):
    """Test get_failed_executions uses default 3-day window."""
    conn, db_path = temp_db_with_logs

    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))

    # Call without days parameter (defaults to 3)
    failed = get_failed_executions()
    assert len(failed) == 2
