"""Tests for Phase 4 - Weekly Summary."""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


TEMPLATE_ROOT = Path(__file__).resolve().parents[2]


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
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))
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
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))
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
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))
    from date_utils import is_day_before_weekend_or_holiday

    # Friday should trigger
    friday = date(2026, 7, 10)
    assert is_day_before_weekend_or_holiday(friday) is True


def test_is_day_before_weekend_or_holiday_monday():
    """Test no trigger on Monday."""
    import sys
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))
    from date_utils import is_day_before_weekend_or_holiday

    # Monday should not trigger
    monday = date(2026, 7, 6)
    assert is_day_before_weekend_or_holiday(monday) is False


def test_get_year_week_format():
    """Test year-week format (ISO 8601)."""
    import sys
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))
    from date_utils import get_year_week

    # 2026-07-06 is Monday of week 28
    monday = date(2026, 7, 6)
    year_week = get_year_week(monday)

    assert year_week == "2026-W28"


# Integration Tests - Weekly Summary Generation

def test_collect_week_summaries(temp_vault, mock_daily_notes, monkeypatch):
    """Test collecting daily summaries for a week."""
    import sys

    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))

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

    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))

    # Mock read_daily
    def mock_read_daily(date_str: str) -> str:
        daily_path = mock_daily_notes / f"{date_str}.md"
        if daily_path.exists():
            return daily_path.read_text()
        return ""

    with patch("weekly_summary.read_daily", side_effect=mock_read_daily):
        with patch("weekly_summary.get_db_connection", return_value=temp_db):
            with patch(
                "weekly_summary.call_llm_raw",
                return_value="- 汇总 Day 1 summary 与 Key achievements 相关进展。（依据：2026-07-06）",
            ):
                from weekly_summary import collect_week_summaries, generate_weekly_summary

                start = date(2026, 7, 6)
                end = date(2026, 7, 12)

                summaries = collect_week_summaries(start, end)
                weekly_text = generate_weekly_summary(summaries)

                assert "依据：2026-07-06" in weekly_text
                assert weekly_text.startswith("- ")


def test_weekly_summary_logs_execution(temp_vault, mock_daily_notes, temp_db):
    """Test weekly summary logs to execution_log."""
    import sys
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))
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
            written = {}
            fake_week_summaries = {
                "2026-07-06": "Day 1 summary: Important events and tasks completed today.\nKey achievements and learnings from 2026-07-06.",
            }

            with patch.object(weekly_summary, "get_db_connection", return_value=temp_db):
                with patch(
                    "weekly_summary.call_llm_raw",
                    return_value="- 汇总 Day 1 summary 与 Key achievements 相关进展。（依据：2026-07-06）",
                ):
                    with patch.object(weekly_summary, "collect_week_summaries", return_value=fake_week_summaries):
                        with patch.object(
                            weekly_summary,
                            "write_weekly_section",
                            side_effect=lambda year_week, target_date, section, content: written.update(
                                {
                                    "year_week": year_week,
                                    "target_date": target_date,
                                    "section": section,
                                    "content": content,
                                }
                            ),
                        ):
                            weekly_summary.main()

            # Check execution log with separate connection
            logger = ExecutionLogger(check_conn, "2026-07-10")
            logs = logger.get_today_logs()

            # Should have one log entry for weekly_summary
            weekly_logs = [log for log in logs if log["step_name"] == "weekly_summary"]
            assert len(weekly_logs) == 1
            assert weekly_logs[0]["status"] == "completed"
            assert written == {
                "year_week": "2026-W28",
                "target_date": "2026-07-10",
                "section": "AI 总结",
                "content": "- 汇总 Day 1 summary 与 Key achievements 相关进展。（依据：2026-07-06）",
            }

            check_conn.close()


def test_weekly_summary_uses_fallback_when_llm_fails(temp_vault, mock_daily_notes, temp_db):
    """Test weekly summary still writes a deterministic report when LLM fails."""
    import json
    import sys

    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))

    with patch.dict("os.environ", {"OBSIDIAN_VAULT": str(temp_vault)}):
        with patch("sys.argv", ["weekly_summary.py", "2026-07-10"]):
            import weekly_summary

            written = {}
            check_conn = sqlite3.connect(temp_db.execute("PRAGMA database_list").fetchone()[2])
            check_conn.row_factory = sqlite3.Row

            with patch.object(weekly_summary, "get_db_connection", return_value=temp_db):
                with patch("weekly_summary.call_llm_raw", return_value=""):
                    with patch.object(
                        weekly_summary,
                        "write_weekly_section",
                        side_effect=lambda year_week, target_date, section, content: written.update(
                            {
                                "year_week": year_week,
                                "target_date": target_date,
                                "section": section,
                                "content": content,
                            }
                        ),
                    ):
                        weekly_summary.main()

            logs = check_conn.execute(
                "SELECT status, metadata_json FROM execution_log WHERE step_name='weekly_summary'"
            ).fetchall()

            assert written["year_week"] == "2026-W28"
            assert written["target_date"] == "2026-07-10"
            assert written["section"] == "AI 总结"
            assert "本地 fallback 版周报" in written["content"]
            assert logs[-1]["status"] == "completed"
            assert json.loads(logs[-1]["metadata_json"])["fallback"] is True
            check_conn.close()


def test_validate_weekly_summary_rejects_unsupported_numeric_fact():
    import sys

    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))
    from weekly_summary import validate_weekly_summary

    week_summaries = {
        "2026-07-07": "- 修复 llm_filter 配置\n- 验证内网 backend 可用",
    }
    ok, reason = validate_weekly_summary(
        "- 完成架构升级并将响应延迟降低40%。（依据：2026-07-07）",
        week_summaries,
    )
    assert ok is False
    assert reason.startswith("unsupported_numeric")


def test_generate_weekly_summary_retries_then_succeeds():
    import sys

    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))
    from weekly_summary import generate_weekly_summary

    week_summaries = {
        "2026-07-07": "- 修复 llm_filter 配置\n- 验证内网 backend 可用",
    }
    responses = iter([
        "- 完成架构升级并将响应延迟降低40%。（依据：2026-07-07）",
        "- 修复 llm_filter 配置并验证内网 backend 可用。（依据：2026-07-07）",
    ])

    with patch("weekly_summary.call_llm_raw", side_effect=lambda prompt: next(responses)):
        summary = generate_weekly_summary(week_summaries)

    assert "修复 llm_filter 配置" in summary
    assert "依据：2026-07-07" in summary


def test_weekly_summary_falls_back_when_validation_fails_twice(temp_vault, mock_daily_notes, temp_db):
    import json
    import sys

    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))

    with patch.dict("os.environ", {"OBSIDIAN_VAULT": str(temp_vault)}):
        with patch("sys.argv", ["weekly_summary.py", "2026-07-10"]):
            import weekly_summary

            written = {}
            check_conn = sqlite3.connect(temp_db.execute("PRAGMA database_list").fetchone()[2])
            check_conn.row_factory = sqlite3.Row
            fake_week_summaries = {
                "2026-07-06": "Day 1 summary: Important events and tasks completed today.\nKey achievements and learnings from 2026-07-06.",
                "2026-07-07": "Day 2 summary: Important events and tasks completed today.\nKey achievements and learnings from 2026-07-07.",
            }

            with patch.object(weekly_summary, "get_db_connection", return_value=temp_db):
                with patch(
                    "weekly_summary.call_llm_raw",
                    side_effect=[
                        "- 完成架构升级并将响应延迟降低40%。（依据：2026-07-06）",
                        "- 形成Q3里程碑并完成V2.0升级。（依据：2026-07-07）",
                    ],
                ):
                    with patch.object(weekly_summary, "collect_week_summaries", return_value=fake_week_summaries):
                        with patch.object(
                            weekly_summary,
                            "write_weekly_section",
                            side_effect=lambda year_week, target_date, section, content: written.update(
                                {
                                    "year_week": year_week,
                                    "target_date": target_date,
                                    "section": section,
                                    "content": content,
                                }
                            ),
                        ):
                            weekly_summary.main()

            logs = check_conn.execute(
                "SELECT status, metadata_json FROM execution_log WHERE step_name='weekly_summary'"
            ).fetchall()

            assert "本地 fallback 版周报" in written["content"]
            assert logs[-1]["status"] == "completed"
            assert json.loads(logs[-1]["metadata_json"])["fallback"] is True
            check_conn.close()


def test_weekly_summary_skips_non_friday(temp_vault, mock_daily_notes, temp_db, capsys):
    """Test weekly summary skips execution on non-Friday when not explicit."""
    import sys
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))

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
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub"))
    sys.path.insert(0, str(TEMPLATE_ROOT / "agent/data-hub" / "scripts" / "archive"))

    with patch.dict("os.environ", {"OBSIDIAN_VAULT": str(temp_vault)}):
        from weekly_summary import collect_week_summaries

        start = date(2026, 8, 1)
        end = date(2026, 8, 7)

        summaries = collect_week_summaries(start, end)

        # No daily notes for this week
        assert len(summaries) == 0
