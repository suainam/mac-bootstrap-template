#!/usr/bin/env python3
"""
Generate candidate review items from extracted external-source items and write a
daily review queue markdown file into the Obsidian vault.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent
if str(DATA_HUB_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_HUB_DIR))

from candidate_review_io import render_candidate_markdown, stable_candidate_id
from candidate_store import (
    fetch_candidates,
    iter_chat_rows,
    iter_source_rows,
    prune_stale_candidates,
    upsert_chat_candidates,
    upsert_candidates,
)
from db_helper import get_db_connection as get_shared_db_connection
from data_hub_config import get_runtime_config
from execution_logger import ExecutionLogger
from llm_filter import filter_candidates_batch, FilterResult
import sqlite3

def _apply_llm_enrichment(
    conn: sqlite3.Connection,
    pairs: list[tuple[dict | sqlite3.Row, FilterResult]],
    target_date: str,
) -> None:
    """Overwrite title/confidence/review_note in DB with LLM-enriched values."""
    now = datetime.now().isoformat(timespec="seconds")
    for candidate, result in pairs:
        if result.title_summary:
            if isinstance(candidate, sqlite3.Row):
                extracted_item_id = candidate["extracted_item_id"] if "extracted_item_id" in candidate.keys() else candidate.get("id", "")
                original_content = candidate["content"] if "content" in candidate.keys() else ""
            else:
                extracted_item_id = candidate.get("extracted_item_id") or candidate.get("id", "")
                original_content = candidate.get("content", "")
                
            if getattr(result, "refined_knowledge", None):
                new_content = f"{result.refined_knowledge}\n\n---\n**原始出处内容**:\n{original_content}"
                conn.execute(
                    """
                    UPDATE knowledge_candidates
                    SET title = ?, confidence = ?, review_note = ?, content = ?, updated_at = ?
                    WHERE extracted_item_id = ? AND candidate_date = ?
                    """,
                    (result.title_summary, result.confidence, result.reason, new_content, now,
                     extracted_item_id, target_date),
                )
            else:
                conn.execute(
                    """
                    UPDATE knowledge_candidates
                    SET title = ?, confidence = ?, review_note = ?, updated_at = ?
                    WHERE extracted_item_id = ? AND candidate_date = ?
                    """,
                    (result.title_summary, result.confidence, result.reason, now,
                     extracted_item_id, target_date),
                )
    conn.commit()


def load_env() -> None:
    return None


load_env()

RUNTIME_CONFIG = get_runtime_config()
OBSIDIAN_VAULT_DIR = RUNTIME_CONFIG.paths.vault_dir
DB_PATH = RUNTIME_CONFIG.paths.db_path
CANDIDATE_DIR = OBSIDIAN_VAULT_DIR / "60_Inbox" / "Candidates"


def main() -> None:
    target_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_shared_db_connection()
    logger = ExecutionLogger(conn, target_date)

    log_id = logger.start("generate_candidates")
    try:
        prune_stale_candidates(conn)
        
        raw_source = list(iter_source_rows(conn, target_date))
        raw_chat = list(iter_chat_rows(conn, target_date))
        
        filtered_source_pairs = filter_candidates_batch(raw_source, "external")
        filtered_chat_pairs = filter_candidates_batch(raw_chat, "chat_response")
        
        source_changed = upsert_candidates(conn, target_date, filtered_source_pairs, stable_candidate_id)
        chat_changed = upsert_chat_candidates(conn, target_date, filtered_chat_pairs, stable_candidate_id)
        
        _apply_llm_enrichment(conn, filtered_source_pairs + filtered_chat_pairs, target_date)
        
        changed = [*source_changed, *chat_changed]
        rows = fetch_candidates(conn, target_date)

        out_path = CANDIDATE_DIR / f"{target_date}.md"
        out_path.write_text(render_candidate_markdown(target_date, rows), encoding="utf-8")
        print(f"[generate_candidates] {target_date}: {len(changed)} upserted, {len(rows)} candidates -> {out_path}")

        logger.complete(log_id, records_affected=len(changed))
    except Exception as e:
        logger.fail(log_id, str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
