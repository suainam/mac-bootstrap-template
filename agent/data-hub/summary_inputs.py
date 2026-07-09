from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from data_hub_config import get_runtime_config, get_summary_output_dir
from summary_calendar import is_workday


PREVIOUS_LEVEL = {
    "weekly": "daily",
    "monthly": "weekly",
    "quarterly": "monthly",
    "yearly": "quarterly",
}


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def previous_level(level: str) -> str:
    if level not in PREVIOUS_LEVEL:
        raise ValueError(f"level has no previous summary layer: {level}")
    return PREVIOUS_LEVEL[level]


def required_summary_dates(level: str, period_start: str, period_end: str, deployment_start: str) -> list[str]:
    start = max(parse_date(period_start), parse_date(deployment_start))
    end = parse_date(period_end)
    if start > end:
        return []

    dates: list[str] = []
    current = start
    while current <= end:
        current_iso = current.isoformat()
        if level != "weekly" or is_workday(current_iso):
            dates.append(current_iso)
        current += timedelta(days=1)
    return dates


def resolve_summary_period_id(level: str, anchor_date: str) -> str:
    dt = parse_date(anchor_date)
    if level == "daily":
        return dt.isoformat()
    if level == "weekly":
        start = dt - timedelta(days=dt.weekday())
        iso = start.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if level == "monthly":
        return f"{dt.year}-{dt.month:02d}"
    if level == "quarterly":
        return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"
    if level == "yearly":
        return f"{dt.year}"
    raise ValueError(f"unsupported summary level: {level}")


def required_previous_periods(
    level: str,
    period_start: str,
    period_end: str,
    deployment_start: str,
) -> list[tuple[str, str, str]]:
    lower = previous_level(level)
    seen: set[str] = set()
    required: list[tuple[str, str, str]] = []
    for anchor in required_summary_dates(level, period_start, period_end, deployment_start):
        period_id = resolve_summary_period_id(lower, anchor)
        if period_id in seen:
            continue
        seen.add(period_id)
        required.append((lower, anchor, period_id))
    return required


def expected_summary_path(level: str, period_id: str) -> Path:
    return get_summary_output_dir(level) / f"{period_id}.md"


def missing_previous_layer(
    level: str,
    period_start: str,
    period_end: str,
    deployment_start: str,
) -> list[tuple[str, str]]:
    missing = []
    for lower, anchor, period_id in required_previous_periods(level, period_start, period_end, deployment_start):
        if not expected_summary_path(lower, period_id).exists():
            missing.append((lower, anchor))
    return missing


def previous_layer_sources(
    level: str,
    period_start: str,
    period_end: str,
    deployment_start: str,
) -> list[dict[str, Any]]:
    config = get_runtime_config()
    sources: list[dict[str, Any]] = []
    for lower, _anchor, period_id in required_previous_periods(level, period_start, period_end, deployment_start):
        path = expected_summary_path(lower, period_id)
        if not path.exists():
            raise RuntimeError(f"missing previous summary layer for {level}: {lower} {period_id}")
        sources.append(
            {
                "source_kind": f"{lower}_summary",
                "source_ref": str(path.relative_to(config.paths.vault_dir)),
                "metadata": {"period_id": period_id},
            }
        )
    return sources
