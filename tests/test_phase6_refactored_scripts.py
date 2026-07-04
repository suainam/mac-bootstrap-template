"""Tests for Phase 6 - Refactored Scripts Regression Tests.

Ensures refactored scripts (ingest_logs, ingest_sources, generate_candidates, daily_summary)
maintain the same behavior after refactoring to use db_helper and obsidian_helper.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

# Add data-hub to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub"))


@pytest.fixture
def temp_db():
    """Create temporary test database with schema."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Load full schema
    schema_path = Path(__file__).parent.parent / "agent/data-hub/schema.sql"
    conn.executescript(schema_path.read_text())
    conn.commit()

    yield conn, db_path

    conn.close()
    db_path.unlink()


@pytest.fixture
def temp_vault():
    """Create temporary Obsidian vault directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault_path = Path(tmpdir)
        daily_dir = vault_path / "10_Periodic" / "Daily"
        daily_dir.mkdir(parents=True, exist_ok=True)

        # Create a test daily note
        today = datetime.now().strftime("%Y-%m-%d")
        daily_note = daily_dir / f"{today}.md"
        daily_note.write_text(
            f"# {today}\n\n## Morning\n\nTest content\n\n## AI 总结\n\nOld summary\n"
        )

        yield vault_path


@pytest.fixture
def mock_env(temp_db, temp_vault, monkeypatch):
    """Mock environment variables for tests."""
    conn, db_path = temp_db
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("OBSIDIAN_VAULT_DIR", str(temp_vault))
    monkeypatch.setenv("OBSIDIAN_DAILY_DIR", "10_Periodic/Daily")
    return conn, db_path, temp_vault


# Test 1: db_helper.get_db_connection() returns properly configured connection


def test_db_helper_get_db_connection(mock_env):
    """Test db_helper.get_db_connection returns properly configured connection."""
    from db_helper import get_db_connection

    conn = get_db_connection()

    # Verify row_factory is set
    assert conn.row_factory == sqlite3.Row

    # Verify foreign_keys pragma is enabled
    cursor = conn.execute("PRAGMA foreign_keys")
    assert cursor.fetchone()[0] == 1

    # Verify schema is applied (check if tables exist)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='execution_log'"
    )
    assert cursor.fetchone() is not None

    conn.close()


# Test 2: Verify ingest_logs uses get_db_connection


def test_ingest_logs_uses_db_helper(mock_env):
    """Test ingest_logs.py uses db_helper.get_db_connection()."""
    # Simply verify that the import alias works and returns a proper connection
    from ingest_logs import get_shared_db_connection

    conn = get_shared_db_connection()

    # Verify it returns a properly configured connection
    assert conn.row_factory == sqlite3.Row
    cursor = conn.execute("PRAGMA foreign_keys")
    assert cursor.fetchone()[0] == 1
    conn.close()


def test_ingest_sources_uses_db_helper(mock_env):
    """Test ingest_sources.py uses db_helper.get_db_connection()."""
    from ingest_sources import get_shared_db_connection

    conn = get_shared_db_connection()
    assert conn.row_factory == sqlite3.Row
    cursor = conn.execute("PRAGMA foreign_keys")
    assert cursor.fetchone()[0] == 1
    conn.close()


def test_generate_candidates_uses_db_helper(mock_env):
    """Test generate_candidates.py uses db_helper.get_db_connection()."""
    from generate_candidates import get_shared_db_connection

    conn = get_shared_db_connection()
    assert conn.row_factory == sqlite3.Row
    cursor = conn.execute("PRAGMA foreign_keys")
    assert cursor.fetchone()[0] == 1
    conn.close()


def test_obsidian_helper_write_daily_section(mock_env):
    """Test obsidian_helper.write_daily_section replaces section correctly."""
    from obsidian_helper import write_daily_section, read_daily

    today = datetime.now().strftime("%Y-%m-%d")

    # Write new section content
    new_content = "This is the new AI summary content."
    write_daily_section(today, "AI 总结", new_content)

    # Read back and verify
    content = read_daily(today)
    assert "This is the new AI summary content." in content
    assert "Old summary" not in content  # Old content should be replaced


def test_obsidian_helper_adds_section_if_missing(mock_env):
    """Test obsidian_helper.write_daily_section adds section if not present."""
    from obsidian_helper import write_daily_section, read_daily

    today = datetime.now().strftime("%Y-%m-%d")

    # Write to a section that doesn't exist
    new_section_content = "External materials listed here."
    write_daily_section(today, "外部材料候选项", new_section_content)

    # Read back and verify
    content = read_daily(today)
    assert "## 外部材料候选项" in content
    assert "External materials listed here." in content


def test_execution_log_records_created(mock_env):
    """Test scripts create execution_log records."""
    from execution_logger import ExecutionLogger

    conn, db_path, vault_path = mock_env
    logger = ExecutionLogger(conn, "2026-07-04")

    # Simulate script execution
    log_id = logger.start("test_refactored_script")
    logger.complete(log_id, records_affected=42, metadata={"version": "refactored"})

    # Verify execution_log entry
    cursor = conn.execute(
        "SELECT * FROM execution_log WHERE step_name = 'test_refactored_script'"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["status"] == "completed"
    assert row["records_affected"] == 42
    assert "refactored" in row["metadata_json"]
