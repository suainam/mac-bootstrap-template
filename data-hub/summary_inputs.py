"""SQLite-only lower-summary dependency resolution."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from summary_calendar import is_workday


PREVIOUS_LEVEL = {"weekly": "daily", "monthly": "weekly", "quarterly": "monthly", "yearly": "quarterly"}


class MissingLowerCoverageError(RuntimeError):
    """Raised when a higher summary lacks a required published lower revision."""


@dataclass(frozen=True)
class LowerRevision:
    revision_id: str
    period_id: str
    artifact_path: str
    coverage_start: str
    coverage_end: str
    item_ids: tuple[str, ...]
    published_at: str


def previous_level(level: str) -> str:
    try:
        return PREVIOUS_LEVEL[level]
    except KeyError as exc:
        raise ValueError(f"level has no previous summary layer: {level}") from exc


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _lower_period_id(level: str, value: date) -> str:
    if level == "daily":
        return value.isoformat()
    if level == "weekly":
        monday = value - timedelta(days=value.weekday())
        iso = monday.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if level == "monthly":
        return f"{value.year}-{value.month:02d}"
    if level == "quarterly":
        return f"{value.year}-Q{(value.month - 1) // 3 + 1}"
    raise ValueError(f"unsupported lower summary level: {level}")


def required_lower_segments(
    *,
    level: str,
    period_start: str,
    coverage_end: str,
    deployment_start: str,
) -> dict[str, tuple[str, str]]:
    lower = previous_level(level)
    start = max(_parse_date(period_start), _parse_date(deployment_start))
    end = _parse_date(coverage_end)
    segments: dict[str, tuple[str, str]] = {}
    current = start
    while current <= end:
        if lower == "daily" and not is_workday(current.isoformat()):
            current += timedelta(days=1)
            continue
        period_id = _lower_period_id(lower, current)
        current_iso = current.isoformat()
        existing = segments.get(period_id)
        segments[period_id] = (
            current_iso if existing is None else min(existing[0], current_iso),
            current_iso if existing is None else max(existing[1], current_iso),
        )
        current += timedelta(days=1)
    return segments


def resolve_lower_revisions(
    *,
    conn: sqlite3.Connection,
    level: str,
    period_start: str,
    period_end: str,
    coverage_end: str,
    deployment_start: str,
    preferred_revision_ids: set[str] | None = None,
) -> list[LowerRevision]:
    """Resolve immutable published revisions without opening their Markdown files."""

    lower = previous_level(level)
    rows = conn.execute(
        """
        SELECT r.revision_id, s.period_id, r.artifact_path, r.coverage_start, r.coverage_end,
               r.published_at,
               GROUP_CONCAT(i.item_id) AS item_ids
        FROM summaries s
        JOIN summary_revisions r ON r.summary_id = s.summary_id
        LEFT JOIN summary_items i ON i.revision_id = r.revision_id
        WHERE s.summary_level = ?
          AND r.publish_status = 'published'
          AND r.coverage_end >= ?
          AND r.coverage_start <= ?
          AND r.coverage_end >= ?
        GROUP BY r.revision_id, s.period_id, r.artifact_path, r.coverage_start, r.coverage_end
        ORDER BY r.coverage_start, s.period_id, r.revision_id
        """,
        (lower, max(period_start, deployment_start), min(period_end, coverage_end), deployment_start),
    ).fetchall()
    revisions = [
        LowerRevision(
            revision_id=str(row["revision_id"]),
            period_id=str(row["period_id"]),
            artifact_path=str(row["artifact_path"]),
            coverage_start=str(row["coverage_start"]),
            coverage_end=str(row["coverage_end"]),
            item_ids=tuple(sorted(filter(None, str(row["item_ids"] or "").split(",")))),
            published_at=str(row["published_at"] or ""),
        )
        for row in rows
    ]
    required = required_lower_segments(
        level=level,
        period_start=period_start,
        coverage_end=min(period_end, coverage_end),
        deployment_start=deployment_start,
    )
    by_period: dict[str, list[LowerRevision]] = {}
    for revision in revisions:
        by_period.setdefault(revision.period_id, []).append(revision)
    selected: list[LowerRevision] = []
    missing: list[str] = []
    for period_id, (required_start, required_end) in sorted(required.items()):
        candidates = [
            revision
            for revision in by_period.get(period_id, [])
            if revision.coverage_start <= required_start and revision.coverage_end >= required_end
        ]
        if not candidates:
            missing.append(f"{period_id}:{required_start}..{required_end}")
            continue
        preferred = [
            revision
            for revision in candidates
            if preferred_revision_ids and revision.revision_id in preferred_revision_ids
        ]
        selected.append(
            min(
                preferred or candidates,
                key=lambda revision: (
                    revision.coverage_end != required_end,
                    revision.coverage_end,
                    revision.published_at,
                    revision.revision_id,
                ),
            )
        )
    if missing:
        raise MissingLowerCoverageError(
            f"missing published {lower} coverage for {level}: {', '.join(missing)}"
        )
    return selected


def current_lower_revision_lineage(
    conn: sqlite3.Connection,
    *,
    level: str,
    period_id: str,
) -> set[str]:
    """Return lower revision IDs already pinned by the current higher revision."""

    if level == "daily":
        return set()
    rows = conn.execute(
        """
        SELECT DISTINCT lower_item.revision_id
        FROM summaries higher
        JOIN summary_items higher_item
          ON higher_item.revision_id = higher.current_revision_id
        JOIN summary_item_support support
          ON support.item_id = higher_item.item_id
        JOIN summary_items lower_item
          ON lower_item.item_id = support.supporting_item_id
        WHERE higher.summary_level = ? AND higher.period_id = ?
        """,
        (level, period_id),
    ).fetchall()
    return {str(row[0]) for row in rows}
