from __future__ import annotations

import sys
from pathlib import Path


DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "agent" / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import run_summary_schedule


def test_planned_workflows_for_normal_workday(monkeypatch):
    monkeypatch.setattr(
        run_summary_schedule.summary_calendar,
        "is_summary_trigger_day",
        lambda level, date: level == "daily",
    )

    assert run_summary_schedule.planned_workflows("2026-07-09") == ["build_daily_summary"]


def test_planned_workflows_for_weekly_trigger(monkeypatch):
    monkeypatch.setattr(
        run_summary_schedule.summary_calendar,
        "is_summary_trigger_day",
        lambda level, date: level in {"daily", "weekly"},
    )

    assert run_summary_schedule.planned_workflows("2026-07-10") == ["build_daily_summary", "build_weekly_summary"]


def test_run_workflow_delegates_to_lifecycle_manager(monkeypatch):
    calls = []

    def fake_run(command, check):
        calls.append(command)
        assert check is True

    monkeypatch.setattr(run_summary_schedule.subprocess, "run", fake_run)

    run_summary_schedule.run_workflow("build_daily_summary", "2026-07-10")

    assert calls[0][-5:] == ["run", "--workflow", "build_daily_summary", "--date", "2026-07-10"]
