from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest


DATA_HUB_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import source_ingest_store
from source_adapters.common import Chunk, Item


@pytest.fixture
def temp_db_and_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    db_path = tmp_path / "agent_history.db"
    vault_dir = tmp_path / "vault"
    (vault_dir / "10_Periodic" / "Daily").mkdir(parents=True, exist_ok=True)
    (vault_dir / "10_Periodic" / "Weekly").mkdir(parents=True, exist_ok=True)
    (vault_dir / "60_Inbox" / "Candidates").mkdir(parents=True, exist_ok=True)
    (vault_dir / "50_Sources" / "Meetings").mkdir(parents=True, exist_ok=True)
    (vault_dir / "50_Sources" / "Wiki-Clips").mkdir(parents=True, exist_ok=True)
    (vault_dir / "50_Sources" / "Mindmaps").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("OBSIDIAN_VAULT_DIR", str(vault_dir))
    monkeypatch.setenv("OBSIDIAN_DAILY_DIR", "10_Periodic/Daily")
    monkeypatch.setenv("GIT_SEARCH_ROOTS", str(tmp_path / "repos"))
    return db_path, vault_dir


def seed_message_and_source_data(db_path: Path, vault_dir: Path) -> None:
    conn = source_ingest_store.get_db_connection(db_path)
    try:
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO sessions (id, agent_type, project_path, start_time, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("sess-1", "codex", "-Users-someone-work-projects-growth", now, now),
        )
        conn.execute(
            "INSERT INTO messages (session_id, timestamp, role, content) VALUES (?, ?, ?, ?)",
            ("sess-1", "2026-07-08T09:00:00", "user", "请复用 growth 实验结论"),
        )
        conn.execute(
            "INSERT INTO messages (session_id, timestamp, role, content) VALUES (?, ?, ?, ?)",
            ("sess-1", "2026-07-08T09:05:00", "user", "请复用 growth 实验结论"),
        )
        source_path = vault_dir / "50_Sources" / "Wiki-Clips" / "2026-07-08_growth.md"
        source_path.write_text("# 增长方案\n决定采用 filename_first\n- 跟进实验窗口\n", encoding="utf-8")
        doc_id = source_ingest_store.upsert_document(
            conn,
            "wiki_page",
            source_path,
            "增长方案",
            "hash-growth",
            {"filename_date": "2026-07-08", "landing_date": "2026-07-08"},
        )
        chunk_ids = source_ingest_store.insert_chunks(
            conn,
            doc_id,
            [
                Chunk(chunk_type="heading", locator="block:1", content="# 增长方案", metadata={}),
                Chunk(chunk_type="paragraph", locator="block:2", content="决定采用 filename_first", metadata={}),
            ],
        )
        source_ingest_store.insert_items(
            conn,
            doc_id,
            chunk_ids,
            [
                Item(item_type="decision", title="采用 filename_first", content="默认按文件名日期归因。", confidence=0.91, chunk_index=1, metadata={}),
                Item(item_type="action", title="跟进实验窗口", content="联系运营确认窗口。", confidence=0.84, chunk_index=1, metadata={}),
            ],
        )
        extracted_item_id = conn.execute(
            "SELECT id FROM extracted_items WHERE document_id = ? ORDER BY rowid LIMIT 1",
            (doc_id,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO knowledge_candidates
                (id, extracted_item_id, source_document_id, candidate_date, candidate_type, status,
                 title, content, confidence, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cand-growth-adr",
                extracted_item_id,
                doc_id,
                "2026-07-08",
                "adr",
                "pending",
                "采用 filename_first",
                "默认按文件名日期归因。",
                0.91,
                json.dumps({"source_type": "wiki_page", "document_title": "增长方案"}, ensure_ascii=False),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
