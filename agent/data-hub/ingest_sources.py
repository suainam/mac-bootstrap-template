#!/usr/bin/env python3
"""
Agent Data Hub - External Source Ingestion

Thin orchestration layer:
- load runtime env
- enumerate source files
- delegate parsing to per-source adapters
- persist normalized chunks/items into SQLite
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from source_adapters import iter_source_files, parse_source
from source_ingest_store import ingest_document
from db_helper import get_db_connection as get_shared_db_connection
from execution_logger import ExecutionLogger


def load_env() -> None:
    env_path = Path.home() / "work/config/mac-bootstrap/private/agent/.obsidian_daily.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


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


def main() -> None:
    execution_date = datetime.now().strftime("%Y-%m-%d")
    conn = get_shared_db_connection()
    logger = ExecutionLogger(conn, execution_date)

    log_id = logger.start("ingest_sources")
    ingested = 0
    total_chunks = 0
    total_items = 0
    try:
        for source_type, path in iter_source_files(OBSIDIAN_VAULT_DIR):
            title, chunks, items, metadata, content_hash = parse_source(source_type, path)
            chunk_count, item_count = ingest_document(
                conn=conn,
                source_type=source_type,
                path=path,
                title=title,
                chunks=chunks,
                items=items,
                metadata=metadata,
                content_hash=content_hash,
            )
            total_chunks += chunk_count
            total_items += item_count
            ingested += 1
            print(f"[ingest_sources] {source_type}: {path.name} -> {chunk_count} chunks, {item_count} items")
        conn.commit()

        print(
            f"[ingest_sources] complete: {ingested} documents, "
            f"{total_chunks} chunks, {total_items} extracted items"
        )
        logger.complete(log_id, records_affected=ingested)
    except Exception as e:
        logger.fail(log_id, str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
