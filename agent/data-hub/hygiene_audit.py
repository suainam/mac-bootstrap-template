#!/usr/bin/env python3
"""
Audit the health of the knowledge lifecycle ledger and its materialized notes.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


def load_env() -> None:
    env_path = Path.home() / "work/config/mac-bootstrap/private/agent/.obsidian_daily.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")


load_env()

OBSIDIAN_VAULT_DIR = Path(
    os.path.expandvars(os.environ.get("OBSIDIAN_VAULT_DIR", str(Path.home() / "work/knowledge")))
)
DB_PATH = Path(
    os.path.expandvars(
        os.environ.get(
            "AGENT_DB_PATH",
            str(Path.home() / "work/config/mac-bootstrap/private/agent/data/agent_history.db"),
        )
    )
)


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_orphan_candidates(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT kc.id, kc.candidate_date, kc.title, kc.status
        FROM knowledge_candidates kc
        LEFT JOIN extracted_items ei ON ei.id = kc.extracted_item_id
        LEFT JOIN source_documents sd ON sd.id = kc.source_document_id
        WHERE ei.id IS NULL OR sd.id IS NULL
        ORDER BY kc.candidate_date ASC, kc.rowid ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_stale_review_items(conn: sqlite3.Connection, stale_before: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, candidate_date, candidate_type, status, title, updated_at
        FROM knowledge_candidates
        WHERE status IN ('pending', 'deferred') AND candidate_date < ?
        ORDER BY candidate_date ASC, rowid ASC
        """,
        (stale_before,),
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_duplicate_knowledge_candidates(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT lower(trim(title)) AS normalized_title, candidate_type, COUNT(*) AS duplicate_count
        FROM knowledge_candidates
        WHERE status = 'accepted' AND candidate_type IN ('adr', 'card')
        GROUP BY lower(trim(title)), candidate_type
        HAVING COUNT(*) > 1
        ORDER BY duplicate_count DESC, normalized_title ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_date_anomalies(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT title, path, metadata_json
        FROM source_documents
        ORDER BY rowid ASC
        """
    ).fetchall()
    anomalies = []
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        filename_date = metadata.get("filename_date")
        landing_date = metadata.get("landing_date")
        if filename_date and landing_date and filename_date != landing_date:
            anomalies.append(
                {
                    "title": row["title"],
                    "path": row["path"],
                    "filename_date": filename_date,
                    "landing_date": landing_date,
                }
            )
    return anomalies


def fetch_broken_materializations(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, candidate_type, title, materialized_path
        FROM knowledge_candidates
        WHERE status = 'accepted' AND materialized_path IS NOT NULL
        ORDER BY candidate_date ASC, rowid ASC
        """
    ).fetchall()
    broken = []
    for row in rows:
        materialized_path = OBSIDIAN_VAULT_DIR / row["materialized_path"]
        if not materialized_path.exists():
            broken.append(
                {
                    "candidate_id": row["id"],
                    "candidate_type": row["candidate_type"],
                    "title": row["title"],
                    "problem": "missing_file",
                    "materialized_path": row["materialized_path"],
                }
            )
            continue
        text = materialized_path.read_text(encoding="utf-8")
        if row["id"] not in text:
            broken.append(
                {
                    "candidate_id": row["id"],
                    "candidate_type": row["candidate_type"],
                    "title": row["title"],
                    "problem": "missing_candidate_marker",
                    "materialized_path": row["materialized_path"],
                }
            )
    return broken


def build_audit_report(stale_before: str) -> dict:
    if not DB_PATH.exists():
        return {
            "stale_before": stale_before,
            "orphan_candidates": [],
            "stale_review_items": [],
            "duplicate_knowledge_candidates": [],
            "date_anomalies": [],
            "broken_materializations": [],
            "repair_recommendations": ["SQLite ledger not found. Run the ingest workflow before auditing."],
        }

    conn = get_db_connection()
    try:
        orphan_candidates = fetch_orphan_candidates(conn)
        stale_review_items = fetch_stale_review_items(conn, stale_before)
        duplicate_candidates = fetch_duplicate_knowledge_candidates(conn)
        date_anomalies = fetch_date_anomalies(conn)
        broken_materializations = fetch_broken_materializations(conn)
    finally:
        conn.close()

    recommendations: list[str] = []
    if orphan_candidates:
        recommendations.append("Run candidate pruning or re-ingest the missing source documents before the next review cycle.")
    if stale_review_items:
        recommendations.append("Review pending or deferred candidates older than the audit threshold and either accept, reject, or clean them up.")
    if duplicate_candidates:
        recommendations.append("Merge duplicate accepted ADR/Card candidates or supersede them with a single canonical note.")
    if date_anomalies:
        recommendations.append("Verify filename-first attribution for documents whose filename_date and landing_date diverge.")
    if broken_materializations:
        recommendations.append("Repair missing materialized files or restore candidate_id markers so idempotent promotion still works.")
    if not recommendations:
        recommendations.append("No hygiene issues found in the current audit window.")

    return {
        "stale_before": stale_before,
        "orphan_candidates": orphan_candidates,
        "stale_review_items": stale_review_items,
        "duplicate_knowledge_candidates": duplicate_candidates,
        "date_anomalies": date_anomalies,
        "broken_materializations": broken_materializations,
        "repair_recommendations": recommendations,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the health of the knowledge lifecycle ledger.")
    parser.add_argument("--stale-before", required=True)
    parser.add_argument("--output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_audit_report(args.stale_before)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
