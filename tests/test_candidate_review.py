import sys
from datetime import datetime
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(SCRIPTS_DIR))

import candidate_store
import source_ingest_store
from candidate_review_io import parse_candidate_review, render_candidate_markdown, suggested_materialized_path


def test_render_candidate_markdown_keeps_machine_readable_fields():
    rows = [
        {
            "id": "cand_demo_daily",
            "candidate_type": "daily",
            "status": "pending",
            "title": "跟进门店实验",
            "content": "联系运营确认实验窗口。",
            "confidence": 0.91,
            "metadata_json": '{"source_type":"meeting_note","document_title":"门店实验周会"}',
            "materialized_path": None,
        },
        {
            "id": "cand_demo_adr",
            "candidate_type": "adr",
            "status": "accepted",
            "title": "采用 filename_first 归因",
            "content": "默认按文件名日期归因。",
            "confidence": 0.88,
            "metadata_json": '{"source_type":"wiki_page","document_title":"知识库方案"}',
            "materialized_path": "40_Knowledge/ADR/2026-07-04-filename-first.md",
        },
    ]

    rendered = render_candidate_markdown("2026-07-04", rows)

    assert "# Candidate Review 2026-07-04" in rendered
    assert "- candidate_id: `cand_demo_daily`" in rendered
    assert "- review_action: `pending`" in rendered
    assert "- review_action: `accept`" in rendered
    assert "40_Knowledge/ADR/2026-07-04-filename-first.md" in rendered


def test_parse_candidate_review_reads_updated_actions(tmp_path: Path):
    review_path = tmp_path / "2026-07-04.md"
    review_path.write_text(
        """
---
type: candidate-review
date: 2026-07-04
status: active
---

# Candidate Review 2026-07-04

## DAILY

### 跟进门店实验
- candidate_id: `cand_daily`
- status: `pending`
- review_action: `accept`
- confidence: `0.91`
- source: `meeting_note` / `门店实验周会`
- suggested_action: `daily`
- suggested_path: `10_Periodic/Daily/2026-07-04.md`
- review_note: 需要当天落日报

```text
联系运营确认实验窗口。
```
""".strip(),
        encoding="utf-8",
    )

    items = parse_candidate_review(review_path)

    assert len(items) == 1
    assert items[0].candidate_id == "cand_daily"
    assert items[0].review_action == "accept"
    assert items[0].review_note == "需要当天落日报"


def test_suggested_materialized_path_uses_slug_for_knowledge_notes():
    assert suggested_materialized_path("2026-07-04", "daily", "cand_demo", "跟进门店实验") == "10_Periodic/Daily/2026-07-04.md"
    assert suggested_materialized_path("2026-07-04", "adr", "cand_demo", "Use filename first") == "40_Knowledge/ADR/2026-07-04-use-filename-first.md"


def _seed_chat_messages(tmp_path: Path):
    conn = source_ingest_store.get_db_connection(tmp_path / "agent_history.db")
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO sessions (id, agent_type, project_path, start_time, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("chat-session", "codex", "/work/config/mac-bootstrap", now, now),
    )
    conn.executemany(
        "INSERT INTO messages (session_id, timestamp, role, content) VALUES (?, ?, ?, ?)",
        [
            ("chat-session", "2026-07-04T09:00:00", "user", "决定采用 chat candidates 保守 pending 策略。"),
            ("chat-session", "2026-07-04T09:10:00", "user", "待办：补充 chat candidate 回归测试。"),
            ("chat-session", "2026-07-04T09:20:00", "user", "风险：聊天记录噪音会污染长期知识库。"),
            ("chat-session", "2026-07-04T09:30:00", "user", "今天整理了一下上下文。"),
        ],
    )
    conn.commit()
    return conn


def test_chat_messages_generate_pending_candidates_without_sources(tmp_path: Path):
    conn = _seed_chat_messages(tmp_path)

    rows = candidate_store.iter_chat_rows(conn, "2026-07-04")
    changed = candidate_store.upsert_chat_candidates(conn, "2026-07-04", rows, lambda item_id, date, typ: f"cand_{item_id}_{date}_{typ}")
    candidates = candidate_store.fetch_candidates(conn, "2026-07-04")
    conn.close()

    assert len(rows) == 3
    assert len(changed) == 3
    by_type = {row["candidate_type"]: row for row in candidates}
    assert set(by_type) == {"adr", "daily", "card"}
    assert all(row["status"] == "pending" for row in candidates)
    assert all('"source_kind": "chat_message"' in row["metadata_json"] for row in candidates)


def test_prune_stale_candidates_keeps_existing_chat_message_and_removes_deleted_one(tmp_path: Path):
    conn = _seed_chat_messages(tmp_path)
    rows = candidate_store.iter_chat_rows(conn, "2026-07-04")
    candidate_store.upsert_chat_candidates(conn, "2026-07-04", rows[:2], lambda item_id, date, typ: f"cand_{item_id}_{date}_{typ}")
    deleted_message_id = rows[0]["message_id"]
    kept_message_id = rows[1]["message_id"]

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM messages WHERE id = ?", (deleted_message_id,))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()

    candidate_store.prune_stale_candidates(conn)
    remaining = conn.execute("SELECT metadata_json FROM knowledge_candidates").fetchall()
    conn.close()

    assert len(remaining) == 1
    assert f'"message_id": {kept_message_id}' in remaining[0]["metadata_json"]


def test_render_candidate_markdown_shows_chat_source_and_message_trace():
    rows = [
        {
            "id": "cand_chat",
            "extracted_item_id": "chatmsg_1",
            "candidate_type": "adr",
            "status": "pending",
            "title": "采用 chat candidates",
            "content": "决定采用 chat candidates 保守 pending 策略。",
            "confidence": 0.75,
            "metadata_json": (
                '{"source_kind":"chat_message","source_type":"chat_message","message_id":42,'
                '"agent_type":"codex","project_path":"/work/config/mac-bootstrap","timestamp":"2026-07-04T09:00:00"}'
            ),
            "materialized_path": None,
        },
    ]

    rendered = render_candidate_markdown("2026-07-04", rows)

    assert "- source: `chat_message` / `codex` / `/work/config/mac-bootstrap` / `2026-07-04T09:00:00`" in rendered
    assert "- trace: `message:42`" in rendered
