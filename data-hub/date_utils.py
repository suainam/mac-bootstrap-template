"""Date utilities for workday and holiday detection."""
from __future__ import annotations

from datetime import date, datetime, timedelta


def is_workday(target_date: str | date) -> bool:
    """Check if date is a workday (using chinese_calendar if available, else Mon-Fri)."""
    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    try:
        import chinese_calendar

        return chinese_calendar.is_workday(target_date)
    except ImportError:
        # Fallback: Mon-Fri without holiday detection
        return target_date.weekday() < 5


def get_week_range(target_date: str | date) -> tuple[date, date]:
    """Get start and end date of the week containing target_date."""
    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    # ISO week: Monday = 0, Sunday = 6
    start = target_date - timedelta(days=target_date.weekday())
    end = start + timedelta(days=6)
    return start, end


def get_year_week(target_date: str | date) -> str:
    """Get ISO year-week string (YYYY-Www) for target_date."""
    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    year, week, _ = target_date.isocalendar()
    return f"{year}-W{week:02d}"


def is_day_before_weekend_or_holiday(target_date: str | date) -> bool:
    """Check if target_date is the last workday before weekend or holiday."""
    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    if not is_workday(target_date):
        return False

    next_day = target_date + timedelta(days=1)
    return not is_workday(next_day)
