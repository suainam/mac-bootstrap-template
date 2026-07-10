"""SQLite-only lower-summary dependency resolution."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


PREVIOUS_LEVEL = {"weekly": "daily", "monthly": "weekly", "quarterly": "monthly", "yearly": "quarterly"}


@dataclass(frozen=True)
class LowerRevision:
    revision_id: str
    period_id: str
    artifact_path: str
    coverage_start: str
    coverage_end: str


def previous_level(level: str) -> str:
    try:
        return PREVIOUS_LEVEL[level]
    except KeyError as exc:
        raise ValueError(f"level has no previous summary layer: {level}") from exc


def resolve_lower_revisions(
    *,
    conn: sqlite3.Connection,
    level: str,
    period_start: str,
    period_end: str,
    coverage_end: str,
    deployment_start: str,
) -> list[LowerRevision]:
    """Resolve immutable published revisions without opening their Markdown files."""

    lower = previous_level(level)
    rows = conn.execute(
        """
        SELECT r.revision_id, s.period_id, r.artifact_path, r.coverage_start, r.coverage_end
        FROM summaries s
        JOIN summary_revisions r ON r.revision_id = s.current_revision_id
        WHERE s.summary_level = ?
          AND r.publish_status = 'published'
          AND r.coverage_end >= ?
          AND r.coverage_start <= ?
          AND r.coverage_end >= ?
        ORDER BY r.coverage_start, s.period_id, r.revision_id
        """,
        (lower, max(period_start, deployment_start), min(period_end, coverage_end), deployment_start),
    ).fetchall()
    return [
        LowerRevision(
            revision_id=str(row["revision_id"]),
            period_id=str(row["period_id"]),
            artifact_path=str(row["artifact_path"]),
            coverage_start=str(row["coverage_start"]),
            coverage_end=str(row["coverage_end"]),
        )
        for row in rows
    ]
