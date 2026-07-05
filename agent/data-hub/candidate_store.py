from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from claim_extraction import CHAT_RESPONSE_SOURCE_KIND, classify_chat_response
from source_dates import document_matches_target


def load_env() -> None:
    return None


load_env()

CHAT_SOURCE_TYPE = CHAT_RESPONSE_SOURCE_KIND
CHAT_PARSER_VERSION = "chat-answer-v2"
LEGACY_CHAT_SOURCE_TYPE = "chat_message"
LEGACY_CHAT_PARSER_VERSION = "chat-claim-v1"


def get_db_connection() -> sqlite3.Connection:
    """Get shared DB connection using db_helper."""
    from db_helper import get_db_connection as get_shared_db_connection
    return get_shared_db_connection()


def candidate_type_for(item_type: str, confidence: float) -> str | None:
    if item_type == "decision":
        return "adr"
    if item_type in {"action", "open_loop"}:
        return "daily"
    if item_type in {"fact", "summary", "topic", "risk"} and confidence >= 0.65:
        return "card"
    return None


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def chat_candidate_type_for(claim_type: str) -> str | None:
    if claim_type == "decision":
        return "adr"
    if claim_type in {"action", "open_loop"}:
        return "daily"
    if claim_type == "risk":
        return "card"
    return None


def is_chat_source_kind(source_kind: str | None) -> bool:
    return source_kind in {CHAT_SOURCE_TYPE, LEGACY_CHAT_SOURCE_TYPE}


def truncate_background(text: str | None, limit: int = 300) -> str:
    if not text:
        return ""
    compact = " ".join(str(text).split())
    return compact[:limit]


def prune_legacy_chat_projection(conn: sqlite3.Connection) -> None:
    """Remove v1 user-question chat projections before rebuilding reply-based ones."""
    conn.execute(
        """
        DELETE FROM source_documents
        WHERE source_type = ? AND parser_version = ?
        """,
        (LEGACY_CHAT_SOURCE_TYPE, LEGACY_CHAT_PARSER_VERSION),
    )


def prune_stale_candidates(conn: sqlite3.Connection) -> None:
    stale_ids: list[str] = []
    cursor = conn.execute(
        """
        SELECT kc.id, kc.candidate_date, kc.metadata_json AS candidate_metadata_json,
               sd.path, sd.version_tag, sd.captured_at, sd.metadata_json
        FROM knowledge_candidates kc
        LEFT JOIN extracted_items ei ON ei.id = kc.extracted_item_id
        LEFT JOIN source_documents sd ON sd.id = kc.source_document_id
        """
    )
    for row in cursor.fetchall():
        candidate_metadata = json.loads(row["candidate_metadata_json"] or "{}")
        if is_chat_source_kind(candidate_metadata.get("source_kind")):
            message_id = candidate_metadata.get("message_id")
            if not message_id:
                stale_ids.append(row["id"])
                continue
            exists = conn.execute("SELECT 1 FROM messages WHERE id = ?", (message_id,)).fetchone()
            if not exists:
                stale_ids.append(row["id"])
            continue

        if row["path"] is None:
            stale_ids.append(row["id"])
            continue
        if not document_matches_target(
            row["path"],
            row["version_tag"],
            row["captured_at"],
            row["metadata_json"],
            row["candidate_date"],
        ):
            stale_ids.append(row["id"])

    if stale_ids:
        conn.executemany("DELETE FROM knowledge_candidates WHERE id = ?", [(candidate_id,) for candidate_id in stale_ids])
        conn.commit()


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
        if row["source_type"] not in {CHAT_SOURCE_TYPE, LEGACY_CHAT_SOURCE_TYPE}
        and document_matches_target(
            row["path"],
            row["version_tag"],
            row["captured_at"],
            row["metadata_json"],
            target_date,
        )
    ]


def iter_chat_rows(conn: sqlite3.Connection, target_date: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT m.id AS message_id, m.session_id, m.timestamp, m.content,
               s.agent_type, s.project_path,
               (
                   SELECT u.id
                   FROM messages u
                   WHERE u.session_id = m.session_id
                     AND u.role = 'user'
                     AND (u.timestamp < m.timestamp OR (u.timestamp = m.timestamp AND u.id < m.id))
                   ORDER BY u.timestamp DESC, u.id DESC
                   LIMIT 1
               ) AS background_message_id,
               (
                   SELECT u.content
                   FROM messages u
                   WHERE u.session_id = m.session_id
                     AND u.role = 'user'
                     AND (u.timestamp < m.timestamp OR (u.timestamp = m.timestamp AND u.id < m.id))
                   ORDER BY u.timestamp DESC, u.id DESC
                   LIMIT 1
               ) AS background_prompt
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE m.role = 'assistant' AND m.timestamp LIKE ?
        ORDER BY m.timestamp ASC, m.id ASC
        """,
        (f"{target_date}%",),
    ).fetchall()

    candidates = []
    for row in rows:
        classified = classify_chat_response(row["content"])
        if classified is None:
            continue
        claim_type, confidence, reason = classified
        candidate_type = chat_candidate_type_for(claim_type)
        if candidate_type is None:
            continue
        title = str(row["content"]).splitlines()[0].strip()[:80]
        candidates.append(
            {
                "message_id": int(row["message_id"]),
                "session_id": row["session_id"],
                "timestamp": row["timestamp"],
                "content": row["content"],
                "title": title or f"chat-message-{row['message_id']}",
                "claim_type": claim_type,
                "candidate_type": candidate_type,
                "confidence": confidence,
                "agent_type": row["agent_type"],
                "project_path": row["project_path"],
                "background_message_id": row["background_message_id"],
                "background_prompt": truncate_background(row["background_prompt"]),
                "why_candidate": reason,
            }
        )
    return candidates


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


def upsert_chat_candidates(
    conn: sqlite3.Connection,
    target_date: str,
    rows: list[dict],
    build_candidate_id,
) -> list[dict]:
    now = datetime.now().isoformat(timespec="seconds")
    inserted_or_updated = []
    prune_legacy_chat_projection(conn)
    for row in rows:
        message_id = str(row["message_id"])
        session_id = str(row["session_id"])
        document_id = stable_id("chatdoc", session_id)
        document_path = f"chat-response://{session_id}"
        extracted_item_id = stable_id("chatmsg", message_id, row["claim_type"])
        content = str(row["content"])
        document_metadata = {
            "source_kind": CHAT_SOURCE_TYPE,
            "agent_type": row["agent_type"],
            "project_path": row["project_path"],
            "parser_version": CHAT_PARSER_VERSION,
        }
        item_metadata = {
            "source_kind": CHAT_SOURCE_TYPE,
            "message_id": row["message_id"],
            "session_id": row["session_id"],
            "agent_type": row["agent_type"],
            "project_path": row["project_path"],
            "timestamp": row["timestamp"],
            "claim_type": row["claim_type"],
            "response_role": "assistant",
            "background_message_id": row["background_message_id"],
            "background_prompt": row["background_prompt"],
            "why_candidate": row["why_candidate"],
        }
        conn.execute(
            """
            INSERT INTO source_documents
                (id, source_type, title, path, content_hash, version_tag, captured_at, parser_version, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                title=excluded.title,
                content_hash=excluded.content_hash,
                version_tag=excluded.version_tag,
                captured_at=excluded.captured_at,
                parser_version=excluded.parser_version,
                metadata_json=excluded.metadata_json
            """,
            (
                document_id,
                CHAT_SOURCE_TYPE,
                f"Chat session {session_id}",
                document_path,
                stable_id("hash", session_id, str(row["timestamp"]), content),
                str(row["timestamp"]),
                str(row["timestamp"]),
                CHAT_PARSER_VERSION,
                json.dumps(document_metadata, ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            INSERT INTO extracted_items
                (id, document_id, chunk_id, item_type, title, content, confidence, status, metadata_json)
            VALUES (?, ?, NULL, ?, ?, ?, ?, 'candidate', ?)
            ON CONFLICT(id) DO UPDATE SET
                document_id=excluded.document_id,
                item_type=excluded.item_type,
                title=excluded.title,
                content=excluded.content,
                confidence=excluded.confidence,
                metadata_json=excluded.metadata_json
            """,
            (
                extracted_item_id,
                document_id,
                row["claim_type"],
                row["title"],
                content,
                float(row["confidence"]),
                json.dumps(item_metadata, ensure_ascii=False),
            ),
        )
        candidate_id = build_candidate_id(extracted_item_id, target_date, row["candidate_type"])
        candidate_metadata = {
            "source_kind": CHAT_SOURCE_TYPE,
            "source_type": CHAT_SOURCE_TYPE,
            "document_title": f"Chat session {session_id}",
            "path": document_path,
            "item_type": row["claim_type"],
            "message_id": row["message_id"],
            "session_id": row["session_id"],
            "agent_type": row["agent_type"],
            "project_path": row["project_path"],
            "timestamp": row["timestamp"],
            "response_role": "assistant",
            "background_message_id": row["background_message_id"],
            "background_prompt": row["background_prompt"],
            "why_candidate": row["why_candidate"],
            "parser_version": CHAT_PARSER_VERSION,
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
                extracted_item_id,
                document_id,
                target_date,
                row["candidate_type"],
                row["title"],
                content,
                float(row["confidence"]),
                json.dumps(candidate_metadata, ensure_ascii=False),
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
