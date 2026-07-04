from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from source_dates import document_matches_target


def load_env() -> None:
    env_path = Path.home() / "work/config/mac-bootstrap/private/agent/.obsidian_daily.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")


load_env()

DB_PATH = Path(os.path.expandvars(os.environ.get("AGENT_DB_PATH", str(Path.home() / "work/config/mac-bootstrap/private/agent/data/agent_history.db"))))


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema_path = Path(__file__).parent / "schema.sql"
    conn.executescript(schema_path.read_text())
    return conn


def candidate_type_for(item_type: str, confidence: float) -> str | None:
    if item_type == "decision":
        return "adr"
    if item_type in {"action", "open_loop"}:
        return "daily"
    if item_type in {"fact", "summary", "topic", "risk"} and confidence >= 0.65:
        return "card"
    return None


def prune_stale_candidates(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        DELETE FROM knowledge_candidates
        WHERE NOT EXISTS (
                SELECT 1 FROM extracted_items
                WHERE extracted_items.id = knowledge_candidates.extracted_item_id
            )
           OR NOT EXISTS (
                SELECT 1 FROM source_documents
                WHERE source_documents.id = knowledge_candidates.source_document_id
            )
        """
    )


def iter_source_rows(conn: sqlite3.Connection, target_date: str) -> list[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT d.id AS document_id, d.source_type, d.title AS document_title, d.path, d.version_tag, d.captured_at,
               i.id AS extracted_item_id, i.item_type, i.title, i.content, i.confidence, i.metadata_json
        FROM source_documents d
        JOIN extracted_items i ON i.document_id = d.id
        ORDER BY d.captured_at DESC, d.rowid DESC, i.rowid ASC
        """
    )
    return [
        row for row in cursor.fetchall()
        if document_matches_target(
            row["path"],
            row["version_tag"],
            row["captured_at"],
            row["metadata_json"],
            target_date,
        )
    ]


def upsert_candidates(
    conn: sqlite3.Connection,
    target_date: str,
    rows: list[sqlite3.Row],
    build_candidate_id,
) -> list[sqlite3.Row]:
    now = datetime.now().isoformat(timespec="seconds")
    inserted_or_updated = []
    for row in rows:
        candidate_type = candidate_type_for(row["item_type"], float(row["confidence"]))
        if not candidate_type:
            continue
        candidate_id = build_candidate_id(row["extracted_item_id"], target_date, candidate_type)
        metadata = {
            "source_type": row["source_type"],
            "document_title": row["document_title"],
            "path": row["path"],
            "item_type": row["item_type"],
            "raw_metadata": json.loads(row["metadata_json"] or "{}"),
        }
        conn.execute(
            """
            INSERT INTO knowledge_candidates
                (id, extracted_item_id, source_document_id, candidate_date, candidate_type, status,
                 title, content, confidence, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(extracted_item_id) DO UPDATE SET
                candidate_date=excluded.candidate_date,
                candidate_type=excluded.candidate_type,
                title=excluded.title,
                content=excluded.content,
                confidence=excluded.confidence,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at
            """,
            (
                candidate_id,
                row["extracted_item_id"],
                row["document_id"],
                target_date,
                candidate_type,
                row["title"],
                row["content"],
                float(row["confidence"]),
                json.dumps(metadata, ensure_ascii=False),
                now,
                now,
            ),
        )
        inserted_or_updated.append(row)
    conn.commit()
    return inserted_or_updated


def fetch_candidates(conn: sqlite3.Connection, target_date: str) -> list[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, extracted_item_id, candidate_type, status, title, content, confidence, metadata_json, materialized_path
        FROM knowledge_candidates
        WHERE candidate_date = ?
        ORDER BY candidate_type ASC, confidence DESC, rowid ASC
        """,
        (target_date,),
    )
    return cursor.fetchall()
