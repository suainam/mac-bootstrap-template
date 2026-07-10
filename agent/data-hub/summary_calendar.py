from __future__ import annotations

from datetime import date, datetime, timedelta

import chinese_calendar


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def is_workday(value: str) -> bool:
    return bool(chinese_calendar.is_workday(parse_date(value)))


def previous_workday(value: str) -> str:
    current = parse_date(value) - timedelta(days=1)
    while not chinese_calendar.is_workday(current):
        current -= timedelta(days=1)
    return current.isoformat()


def next_workday(value: str) -> str:
    current = parse_date(value) + timedelta(days=1)
    while not chinese_calendar.is_workday(current):
        current += timedelta(days=1)
    return current.isoformat()


def is_day_before_non_workday(value: str) -> bool:
    current = parse_date(value)
    return bool(chinese_calendar.is_workday(current)) and not chinese_calendar.is_workday(current + timedelta(days=1))


def is_last_calendar_day_of_month(value: date) -> bool:
    return (value + timedelta(days=1)).month != value.month


def is_last_calendar_day_of_quarter(value: date) -> bool:
    return value.month in {3, 6, 9, 12} and is_last_calendar_day_of_month(value)


def is_last_calendar_day_of_year(value: date) -> bool:
    return value.month == 12 and value.day == 31


def is_summary_trigger_day(level: str, anchor_date: str) -> bool:
    current = parse_date(anchor_date)
    if level == "daily":
        return bool(chinese_calendar.is_workday(current))
    if level == "weekly":
        return is_day_before_non_workday(anchor_date)
    if level == "monthly":
        return is_last_calendar_day_of_month(current)
    if level == "quarterly":
        return is_last_calendar_day_of_quarter(current)
    if level == "yearly":
        return is_last_calendar_day_of_year(current)
    raise ValueError(f"unsupported summary level: {level}")


def should_run_evening_summary(anchor_date: str) -> bool:
    return is_summary_trigger_day("daily", anchor_date)


def should_run_scheduled_event(event: str, anchor_date: str) -> bool:
    """Gate morning/reminder on China workdays; evening dispatch is calendar-driven."""

    if event in {"morning", "reminder"}:
        return is_workday(anchor_date)
    if event == "evening":
        return True
    raise ValueError(f"unsupported scheduled event: {event}")
