from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from source_adapters.common import Chunk, Item
from source_dates import extract_date_prefix
from schema_migrations import ensure_summary_runs_allows_daily


PARSER_VERSION = "source-ingest-v2"


def stable_id(prefix: str, *parts: str) -> str:
    joined = "::".join(parts)
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def get_db_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema_path = Path(__file__).parent / "schema.sql"
    conn.executescript(schema_path.read_text())
    ensure_summary_runs_allows_daily(conn)
    return conn


def get_existing_document(conn: sqlite3.Connection, path: Path) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, content_hash, parser_version
        FROM source_documents
        WHERE path = ?
        """,
        (str(path),),
    ).fetchone()


def get_existing_counts(conn: sqlite3.Connection, document_id: str) -> tuple[int, int]:
    chunk_count = conn.execute(
        "SELECT COUNT(*) FROM document_chunks WHERE document_id = ?",
        (document_id,),
    ).fetchone()[0]
    item_count = conn.execute(
        "SELECT COUNT(*) FROM extracted_items WHERE document_id = ?",
        (document_id,),
    ).fetchone()[0]
    return chunk_count, item_count


def upsert_document(
    conn: sqlite3.Connection,
    source_type: str,
    path: Path,
    title: str,
    content_hash: str,
    metadata: dict,
) -> str:
    doc_id = stable_id("src", source_type, str(path))
    now = datetime.now().isoformat(timespec="seconds")
    version_tag = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    metadata = dict(metadata)
    metadata.setdefault("file_name", path.name)
    metadata.setdefault("filename_date", extract_date_prefix(path.name))
    metadata["version_date"] = version_tag[:10]
    metadata.setdefault("landing_date", now[:10])
    conn.execute(
        """
        INSERT INTO source_documents
            (id, source_type, title, path, content_hash, version_tag, captured_at, parser_version, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            title=excluded.title,
            content_hash=excluded.content_hash,
            version_tag=excluded.version_tag,
            captured_at=source_documents.captured_at,
            parser_version=excluded.parser_version,
            metadata_json=excluded.metadata_json
        """,
        (
            doc_id,
            source_type,
            title,
            str(path),
            content_hash,
            version_tag,
            now,
            PARSER_VERSION,
            json.dumps(metadata, ensure_ascii=False),
        ),
    )
    conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))
    conn.execute("DELETE FROM extracted_items WHERE document_id = ?", (doc_id,))
    return doc_id


def insert_chunks(conn: sqlite3.Connection, document_id: str, chunks: list[Chunk]) -> list[str]:
    chunk_ids: list[str] = []
    for idx, chunk in enumerate(chunks):
        chunk_id = stable_id("chk", document_id, str(idx), chunk.chunk_type, chunk.locator)
        chunk_ids.append(chunk_id)
        conn.execute(
            """
            INSERT INTO document_chunks (id, document_id, chunk_index, chunk_type, locator, content, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                document_id,
                idx,
                chunk.chunk_type,
                chunk.locator,
                chunk.content,
                json.dumps(chunk.metadata, ensure_ascii=False),
            ),
        )
    return chunk_ids


def insert_items(conn: sqlite3.Connection, document_id: str, chunk_ids: list[str], items: list[Item]) -> None:
    for idx, item in enumerate(items):
        chunk_id = chunk_ids[item.chunk_index] if item.chunk_index is not None and item.chunk_index < len(chunk_ids) else None
        item_id = stable_id("itm", document_id, str(idx), item.item_type, item.title)
        conn.execute(
            """
            INSERT INTO extracted_items (id, document_id, chunk_id, item_type, title, content, confidence, status, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?)
            """,
            (
                item_id,
                document_id,
                chunk_id,
                item.item_type,
                item.title,
                item.content,
                item.confidence,
                json.dumps(item.metadata, ensure_ascii=False),
            ),
        )


def ingest_document(
    conn: sqlite3.Connection,
    source_type: str,
    path: Path,
    title: str,
    chunks: list[Chunk],
    items: list[Item],
    metadata: dict,
    content_hash: str,
) -> tuple[int, int]:
    existing = get_existing_document(conn, path)
    if existing and existing["content_hash"] == content_hash and existing["parser_version"] == PARSER_VERSION:
        return get_existing_counts(conn, existing["id"])

    doc_id = upsert_document(conn, source_type, path, title, content_hash, metadata)
    chunk_ids = insert_chunks(conn, doc_id, chunks)
    insert_items(conn, doc_id, chunk_ids, items)
    return len(chunks), len(items)
