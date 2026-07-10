from __future__ import annotations

import sys
from pathlib import Path

DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

from period_summary import resolve_period_coverage


def test_weekly_preholiday_revision_is_provisional_before_week_end():
    result = resolve_period_coverage("weekly", "2026-10-02")

    assert result.period_id == "2026-W40"
    assert result.closure_status == "provisional"
    assert result.coverage_end == "2026-10-02"


def test_daily_coverage_is_closed():
    result = resolve_period_coverage("daily", "2026-07-10")

    assert result.closure_status == "closed"
    assert result.period_start == result.coverage_end
