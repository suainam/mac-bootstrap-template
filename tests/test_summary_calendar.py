from __future__ import annotations

import sys
from pathlib import Path

DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

import summary_calendar


def test_previous_workday_skips_weekend():
    assert summary_calendar.previous_workday("2026-07-13") == "2026-07-10"


def test_weekly_trigger_runs_on_friday_or_pre_holiday():
    assert summary_calendar.is_summary_trigger_day("weekly", "2026-07-10") is True
    assert summary_calendar.is_summary_trigger_day("weekly", "2026-07-09") is False


def test_monthly_quarterly_yearly_trigger_boundaries():
    assert summary_calendar.is_summary_trigger_day("monthly", "2026-07-31") is True
    assert summary_calendar.is_summary_trigger_day("quarterly", "2026-09-30") is True
    assert summary_calendar.is_summary_trigger_day("yearly", "2026-12-31") is True
    assert summary_calendar.is_summary_trigger_day("yearly", "2026-12-30") is False
