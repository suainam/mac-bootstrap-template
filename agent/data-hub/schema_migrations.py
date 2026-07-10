"""One-time SQLite migrations for the Agent Data Hub."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _stable_id(prefix: str, value: str, length: int) -> str:
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _logical_summary_id(level: str, period_id: str) -> str:
    return _stable_id("summary_", f"{level}:{period_id}", 20)


def _revision_id(summary_id: str, input_digest: str) -> str:
    return _stable_id("rev_", f"{summary_id}:{input_digest}", 24)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def _json_object(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"legacy_metadata_raw": raw or ""}
    return value if isinstance(value, dict) else {"legacy_metadata": value}


def ensure_summary_revision_schema(conn: sqlite3.Connection) -> None:
    """Create revision tables and atomically consume the legacy summary tables once."""

    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not _table_exists(conn, "summary_runs"):
        return

    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        legacy_runs = conn.execute("SELECT * FROM summary_runs ORDER BY created_at, id").fetchall()
        has_sources = _table_exists(conn, "summary_run_sources")
        for run in legacy_runs:
            level = str(run["summary_level"])
            period_id = str(run["period_id"])
            summary_id = _logical_summary_id(level, period_id)
            input_digest = f"legacy:{run['id']}"
            revision_id = _revision_id(summary_id, input_digest)
            publish_status = "published" if run["status"] == "completed" else "failed"
            now = str(run["updated_at"] or run["created_at"])
            artifact_path = str(run["output_path"] or "")
            metadata = _json_object(run["metadata_json"])
            metadata.update(
                {
                    "legacy_run_id": str(run["id"]),
                    "legacy_source_mode": str(run["source_mode"]),
                    "legacy_status": str(run["status"]),
                }
            )
            document = {
                "contract_version": "legacy",
                "taxonomy_version": "legacy",
                "policy_version": "legacy",
                "level": level,
                "period": period_id,
                "headline": f"Legacy {level} summary {period_id}",
                "items": [],
            }

            conn.execute(
                """
                INSERT INTO summaries
                    (summary_id, summary_level, period_id, current_revision_id, created_at, updated_at)
                VALUES (?, ?, ?, NULL, ?, ?)
                ON CONFLICT(summary_level, period_id) DO NOTHING
                """,
                (summary_id, level, period_id, str(run["created_at"]), now),
            )
            conn.execute(
                """
                INSERT INTO summary_revisions
                    (revision_id, summary_id, input_digest, coverage_start, coverage_end,
                     closure_status, contract_version, taxonomy_version, policy_version,
                     publish_status, quality_status, document_json, artifact_path, artifact_hash,
                     metadata_json, created_at, published_at)
                VALUES (?, ?, ?, ?, ?, 'closed', 'legacy', 'legacy', 'legacy', ?, 'complete',
                        ?, ?, NULL, ?, ?, ?)
                ON CONFLICT(summary_id, input_digest) DO NOTHING
                """,
                (
                    revision_id,
                    summary_id,
                    input_digest,
                    str(run["period_start"]),
                    str(run["period_end"]),
                    publish_status,
                    json.dumps(document, ensure_ascii=False, sort_keys=True),
                    artifact_path,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    str(run["created_at"]),
                    now if publish_status == "published" else None,
                ),
            )

            if has_sources:
                sources = conn.execute(
                    "SELECT * FROM summary_run_sources WHERE run_id = ? ORDER BY id", (run["id"],)
                ).fetchall()
                for source in sources:
                    group_id = _stable_id(
                        "evg_legacy_",
                        f"{run['id']}:{source['source_kind']}:{source['source_ref']}:{source['id']}",
                        20,
                    )
                    payload = _json_object(source["metadata_json"])
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO summary_evidence_groups
                            (revision_id, evidence_group_id, evidence_kind, normalized_payload_json)
                        VALUES (?, ?, 'legacy', ?)
                        """,
                        (
                            revision_id,
                            group_id,
                            json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO summary_evidence_sources
                            (revision_id, evidence_group_id, source_kind, source_ref,
                             source_claim_id, metadata_json)
                        VALUES (?, ?, ?, ?, '', ?)
                        """,
                        (
                            revision_id,
                            group_id,
                            str(source["source_kind"]),
                            str(source["source_ref"]),
                            json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        ),
                    )

            if publish_status == "published":
                conn.execute(
                    """
                    UPDATE summaries
                    SET current_revision_id = ?, updated_at = ?
                    WHERE summary_id = ?
                    """,
                    (revision_id, now, summary_id),
                )

        if has_sources:
            conn.execute("DROP TABLE summary_run_sources")
        conn.execute("DROP TABLE summary_runs")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def ensure_summary_runs_allows_daily(conn: sqlite3.Connection) -> None:
    """Temporary caller bridge: all connections now run the revision migration."""

    ensure_summary_revision_schema(conn)
