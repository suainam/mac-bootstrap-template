"""Tests for Phase 4 - Weekly Summary."""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


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
    """)
    conn.commit()

    yield conn

    conn.close()
    db_path.unlink()


@pytest.fixture
def temp_vault(tmp_path):
    """Create temporary Obsidian vault structure."""
    vault_path = tmp_path / "vault"
    daily_path = vault_path / "10_Periodic" / "Daily"
    weekly_path = vault_path / "10_Periodic" / "Weekly"

    daily_path.mkdir(parents=True, exist_ok=True)
    weekly_path.mkdir(parents=True, exist_ok=True)

    return vault_path


@pytest.fixture
def mock_daily_notes(temp_vault):
    """Create a week of daily notes."""
    daily_path = temp_vault / "10_Periodic" / "Daily"

    # Create notes for Monday to Friday (2026-07-06 to 2026-07-10)
    for i in range(5):
        target_date = date(2026, 7, 6) + timedelta(days=i)
        date_str = target_date.strftime("%Y-%m-%d")
        note_path = daily_path / f"{date_str}.md"

        content = f"""# {date_str}

## AI 总结

Day {i+1} summary: Important events and tasks completed today.
Key achievements and learnings from {date_str}.

## Tasks
- Task A for day {i+1}
- Task B for day {i+1}

## Notes
Some notes for {date_str}
"""
        note_path.write_text(content)

    return daily_path


# Unit Tests - Date Calculation

def test_get_week_range_monday():
    """Test get_week_range returns Monday-Sunday for any day in week."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub" / "scripts"))
    from date_utils import get_week_range

    # Test with Monday (2026-07-06)
    monday = date(2026, 7, 6)
    start, end = get_week_range(monday)

    assert start == monday
    assert end == date(2026, 7, 12)  # Sunday
    assert (end - start).days == 6


def test_get_week_range_friday():
    """Test get_week_range with Friday returns same week range."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub" / "scripts"))
    from date_utils import get_week_range

    # Test with Friday (2026-07-10)
    friday = date(2026, 7, 10)
    start, end = get_week_range(friday)

    assert start == date(2026, 7, 6)  # Monday
    assert end == date(2026, 7, 12)   # Sunday
    assert (end - start).days == 6


def test_is_day_before_weekend_or_holiday_friday():
    """Test trigger on Friday."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub" / "scripts"))
    from date_utils import is_day_before_weekend_or_holiday

    # Friday should trigger
    friday = date(2026, 7, 10)
    assert is_day_before_weekend_or_holiday(friday) is True


def test_is_day_before_weekend_or_holiday_monday():
    """Test no trigger on Monday."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub" / "scripts"))
    from date_utils import is_day_before_weekend_or_holiday

    # Monday should not trigger
    monday = date(2026, 7, 6)
    assert is_day_before_weekend_or_holiday(monday) is False


def test_get_year_week_format():
    """Test year-week format (ISO 8601)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub" / "scripts"))
    from date_utils import get_year_week

    # 2026-07-06 is Monday of week 28
    monday = date(2026, 7, 6)
    year_week = get_year_week(monday)

    assert year_week == "2026-W28"


# Integration Tests - Weekly Summary Generation

def test_collect_week_summaries(temp_vault, mock_daily_notes, monkeypatch):
    """Test collecting daily summaries for a week."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub" / "scripts"))

    # Mock read_daily to return content from temp_vault
    def mock_read_daily(date_str: str) -> str:
        daily_path = mock_daily_notes / f"{date_str}.md"
        if daily_path.exists():
            return daily_path.read_text()
        return ""

    with patch("weekly_summary.read_daily", side_effect=mock_read_daily):
        from weekly_summary import collect_week_summaries

        start = date(2026, 7, 6)
        end = date(2026, 7, 12)

        summaries = collect_week_summaries(start, end)

        assert len(summaries) == 5  # Monday to Friday
        assert "2026-07-06" in summaries
        assert "2026-07-10" in summaries
        assert "Day 1 summary" in summaries["2026-07-06"]


def test_weekly_summary_content_format(temp_vault, mock_daily_notes, temp_db, monkeypatch):
    """Test weekly summary generates proper format."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub" / "scripts"))

    # Mock read_daily
    def mock_read_daily(date_str: str) -> str:
        daily_path = mock_daily_notes / f"{date_str}.md"
        if daily_path.exists():
            return daily_path.read_text()
        return ""

    with patch("weekly_summary.read_daily", side_effect=mock_read_daily):
        with patch("weekly_summary.get_db_connection", return_value=temp_db):
            with patch("weekly_summary.call_llm_raw", return_value="Weekly summary: Key events and achievements."):
                from weekly_summary import collect_week_summaries, generate_weekly_summary

                start = date(2026, 7, 6)
                end = date(2026, 7, 12)

                summaries = collect_week_summaries(start, end)
                weekly_text = generate_weekly_summary(summaries)

                assert "Weekly summary" in weekly_text
                assert weekly_text != "调用 LLM 失败，未能生成周报。"


def test_weekly_summary_logs_execution(temp_vault, mock_daily_notes, temp_db):
    """Test weekly summary logs to execution_log."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub" / "scripts"))
    from execution_logger import ExecutionLogger

    with patch.dict("os.environ", {"OBSIDIAN_VAULT": str(temp_vault)}):
        # Need to patch get_db_connection BEFORE importing main
        # because main() closes the connection in finally block
        with patch("sys.argv", ["weekly_summary.py", "2026-07-10"]):
            # Import modules first
            import weekly_summary

            # Create a separate connection for checking logs later
            import sqlite3
            check_conn = sqlite3.connect(temp_db.execute("PRAGMA database_list").fetchone()[2])
            check_conn.row_factory = sqlite3.Row

            with patch.object(weekly_summary, "get_db_connection", return_value=temp_db):
                with patch("weekly_summary.call_llm_raw", return_value="Test summary"):
                    with patch.object(weekly_summary, "write_weekly"):
                        weekly_summary.main()

            # Check execution log with separate connection
            logger = ExecutionLogger(check_conn, "2026-07-10")
            logs = logger.get_today_logs()

            # Should have one log entry for weekly_summary
            weekly_logs = [log for log in logs if log["step_name"] == "weekly_summary"]
            assert len(weekly_logs) == 1
            assert weekly_logs[0]["status"] == "completed"

            check_conn.close()


def test_weekly_summary_skips_non_friday(temp_vault, mock_daily_notes, temp_db, capsys):
    """Test weekly summary skips execution on non-Friday when not explicit."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub" / "scripts"))

    with patch.dict("os.environ", {"OBSIDIAN_VAULT": str(temp_vault)}):
        with patch("weekly_summary.get_db_connection", return_value=temp_db):
            # Mock today as Monday (no explicit date, implicit mode)
            with patch("weekly_summary.today_str", return_value="2026-07-06"):
                with patch("sys.argv", ["weekly_summary.py"]):  # No date arg
                    from weekly_summary import main

                    main()

                    captured = capsys.readouterr()
                    assert "不是周五或节前" in captured.out or "跳过" in captured.out


def test_weekly_summary_empty_week(temp_vault, temp_db):
    """Test weekly summary handles empty week (no daily notes)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub"))
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent/data-hub" / "scripts"))

    with patch.dict("os.environ", {"OBSIDIAN_VAULT": str(temp_vault)}):
        from weekly_summary import collect_week_summaries

        start = date(2026, 8, 1)
        end = date(2026, 8, 7)

        summaries = collect_week_summaries(start, end)

        # No daily notes for this week
        assert len(summaries) == 0




