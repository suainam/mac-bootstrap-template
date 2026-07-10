import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


DATA_HUB_DIR = Path(__file__).parent.parent / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import materialize_candidates
import source_ingest_store
from candidate_review_io import ReviewItem
from source_adapters.common import Chunk, Item


def seed_document_with_candidate(tmp_path: Path):
    db_path = tmp_path / "agent_history.db"
    conn = source_ingest_store.get_db_connection(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    try:
        source_path = tmp_path / "2026-07-04_review.md"
        source_path.write_text("决定采用 filename_first。", encoding="utf-8")
        doc_id = source_ingest_store.upsert_document(
            conn,
            "wiki_page",
            source_path,
            "知识库方案",
            "hash-demo",
            {"filename_date": "2026-07-04", "landing_date": "2026-07-04"},
        )
        chunk_ids = source_ingest_store.insert_chunks(
            conn,
            doc_id,
            [Chunk(chunk_type="paragraph", locator="p1", content="决定采用 filename_first。", metadata={})],
        )
        source_ingest_store.insert_items(
            conn,
            doc_id,
            chunk_ids,
            [Item(item_type="decision", title="采用 filename_first", content="默认按文件名日期归因。", confidence=0.92, chunk_index=0, metadata={})],
        )
        extracted_item_id = conn.execute(
            "SELECT id FROM extracted_items WHERE document_id = ?",
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
                "cand_demo_adr",
                extracted_item_id,
                doc_id,
                "2026-07-04",
                "adr",
                "pending",
                "采用 filename_first",
                "默认按文件名日期归因。",
                0.92,
                '{"source_type":"wiki_page","document_title":"知识库方案"}',
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_materialize_note_candidate_is_idempotent(tmp_path: Path):
    note_path = tmp_path / "40_Knowledge" / "Cards" / "2026-07-04-card.md"

    materialize_candidates.materialize_note_candidate(
        note_path,
        "card",
        "2026-07-04",
        "线下实验不能只看销售额",
        "至少同时看销售额和替代率。",
        "meeting_note / 周会",
        "cand_card_demo",
    )
    materialize_candidates.materialize_note_candidate(
        note_path,
        "card",
        "2026-07-04",
        "线下实验不能只看销售额",
        "至少同时看销售额和替代率。",
        "meeting_note / 周会",
        "cand_card_demo",
    )

    text = note_path.read_text(encoding="utf-8")
    assert text.count("candidate_id: cand_card_demo") == 1
    assert text.count("# 线下实验不能只看销售额") == 1


def test_materialize_daily_candidate_inserts_once_into_existing_daily(tmp_path: Path):
    daily_path = tmp_path / "10_Periodic" / "Daily" / "2026-07-04.md"
    daily_path.parent.mkdir(parents=True)
    daily_path.write_text(
        "\n".join(
            [
                "---",
                "type: journal",
                "---",
                "",
                "# 2026-07-04",
                "",
                "## AI 总结",
                "",
                "已有总结",
                "",
            ]
        ),
        encoding="utf-8",
    )

    materialize_candidates.materialize_daily_candidate(
        daily_path,
        "kr_daily_demo",
        "记录知识库分层决策",
        "push/archive/render/obsidian 三层职责需要清晰。",
    )
    materialize_candidates.materialize_daily_candidate(
        daily_path,
        "kr_daily_demo",
        "记录知识库分层决策",
        "push/archive/render/obsidian 三层职责需要清晰。",
    )

    text = daily_path.read_text(encoding="utf-8")
    assert "## 候选事项" in text
    assert text.count("knowledge_candidate:kr_daily_demo") == 1
    assert "## AI 总结" in text


def test_materialize_daily_candidate_creates_daily_file(tmp_path: Path):
    daily_path = tmp_path / "10_Periodic" / "Daily" / "2026-07-04.md"

    materialize_candidates.materialize_daily_candidate(
        daily_path,
        "kr_daily_new",
        "新增日报知识",
        "新增日报知识",
    )

    text = daily_path.read_text(encoding="utf-8")
    assert "type: journal" in text
    assert "# 2026-07-04" in text
    assert text.count("knowledge_candidate:kr_daily_new") == 1


def test_materialize_daily_candidate_supports_common_insert_positions(tmp_path: Path):
    cases = {
        "has_candidates": "## 候选事项\n\n已有事项\n",
        "has_tomorrow": "## 明日计划\n\n继续推进\n",
        "plain": "## 其他\n\n普通内容\n",
    }

    for name, body in cases.items():
        daily_path = tmp_path / f"{name}.md"
        daily_path.write_text(f"# {name}\n\n{body}", encoding="utf-8")

        materialize_candidates.materialize_daily_candidate(
            daily_path,
            f"kr_{name}",
            "补充候选事项",
            "补充候选事项",
        )

        text = daily_path.read_text(encoding="utf-8")
        assert "## 候选事项" in text
        assert text.count(f"knowledge_candidate:kr_{name}") == 1


def test_apply_review_actions_updates_status_and_materialized_path(tmp_path: Path, monkeypatch):
    db_path = seed_document_with_candidate(tmp_path)
    vault_dir = tmp_path / "vault"
    monkeypatch.setattr(materialize_candidates, "OBSIDIAN_VAULT_DIR", vault_dir)

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        changed, materialized = materialize_candidates.apply_review_actions(
            conn,
            "2026-07-04",
            [ReviewItem(candidate_id="cand_demo_adr", title="采用 filename_first", review_action="accept", review_note="进入 ADR")],
        )
        row = conn.execute(
            "SELECT status, materialized_path, review_note FROM knowledge_candidates WHERE id = ?",
            ("cand_demo_adr",),
        ).fetchone()
    finally:
        conn.close()

    assert changed == 1
    assert materialized == 1
    assert row["status"] == "accepted"
    assert row["review_note"] == "进入 ADR"
    assert row["materialized_path"].startswith("40_Knowledge/ADR/")

    note_path = vault_dir / row["materialized_path"]
    assert note_path.exists()
    assert "candidate_id: cand_demo_adr" in note_path.read_text(encoding="utf-8")


def test_materialize_main_does_not_regenerate_candidates(tmp_path: Path, monkeypatch):
    db_path = seed_document_with_candidate(tmp_path)
    vault_dir = tmp_path / "vault"
    candidate_dir = vault_dir / "60_Inbox" / "Candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "2026-07-04.md").write_text(
        "\n".join(
            [
                "---",
                "type: candidate-review",
                "date: 2026-07-04",
                "status: active",
                "---",
                "",
                "## ADR",
                "",
                "### 采用 filename_first",
                "- candidate_id: `cand_demo_adr`",
                "- review_action: `accept`",
                "- review_note: 进入 ADR",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(materialize_candidates, "OBSIDIAN_VAULT_DIR", vault_dir)
    monkeypatch.setattr(materialize_candidates, "CANDIDATE_DIR", candidate_dir)
    monkeypatch.setattr(materialize_candidates, "get_db_connection", lambda: source_ingest_store.get_db_connection(db_path))
    monkeypatch.setattr(materialize_candidates, "sys", SimpleNamespace(argv=["materialize_candidates.py", "2026-07-04"]))

    materialize_candidates.main()

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT status, materialized_path FROM knowledge_candidates WHERE id = ?",
            ("cand_demo_adr",),
        ).fetchone()
    finally:
        conn.close()

    assert row["status"] == "accepted"
    assert row["materialized_path"].startswith("40_Knowledge/ADR/")


def test_materialize_main_materializes_preaccepted_candidate(tmp_path: Path, monkeypatch):
    db_path = seed_document_with_candidate(tmp_path)
    vault_dir = tmp_path / "vault"
    candidate_dir = vault_dir / "60_Inbox" / "Candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        conn.execute(
            """
            UPDATE knowledge_candidates
            SET status = 'accepted', candidate_type = 'card', materialized_path = NULL
            WHERE id = ?
            """,
            ("cand_demo_adr",),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(materialize_candidates, "OBSIDIAN_VAULT_DIR", vault_dir)
    monkeypatch.setattr(materialize_candidates, "CANDIDATE_DIR", candidate_dir)
    monkeypatch.setattr(materialize_candidates, "get_db_connection", lambda: source_ingest_store.get_db_connection(db_path))
    monkeypatch.setattr(materialize_candidates, "sys", SimpleNamespace(argv=["materialize_candidates.py", "2026-07-04"]))

    materialize_candidates.main()

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT status, materialized_path FROM knowledge_candidates WHERE id = ?",
            ("cand_demo_adr",),
        ).fetchone()
    finally:
        conn.close()

    assert row["status"] == "accepted"
    assert row["materialized_path"].startswith("40_Knowledge/Cards/")
    assert (vault_dir / row["materialized_path"]).exists()


def test_materialize_main_materializes_skill_record(tmp_path: Path, monkeypatch):
    db_path = seed_document_with_candidate(tmp_path)
    vault_dir = tmp_path / "vault"
    candidate_dir = vault_dir / "60_Inbox" / "Candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO knowledge_records
                (id, record_type, title, content, agent_type, recorded_at,
                 candidate_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "kr_skill_card",
                "card",
                "知识记录直接落库",
                "对话中确认的知识应进入 knowledge_records。",
                "codex",
                now,
                "2026-07-04",
                "accepted",
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(materialize_candidates, "OBSIDIAN_VAULT_DIR", vault_dir)
    monkeypatch.setattr(materialize_candidates, "CANDIDATE_DIR", candidate_dir)
    monkeypatch.setattr(materialize_candidates, "get_db_connection", lambda: source_ingest_store.get_db_connection(db_path))
    monkeypatch.setattr(materialize_candidates, "sys", SimpleNamespace(argv=["materialize_candidates.py", "2026-07-04"]))

    materialize_candidates.main()

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT materialized_path FROM knowledge_records WHERE id = ?",
            ("kr_skill_card",),
        ).fetchone()
    finally:
        conn.close()

    assert row["materialized_path"].startswith("40_Knowledge/Cards/")
    note_path = vault_dir / row["materialized_path"]
    assert "skill-record: codex" in note_path.read_text(encoding="utf-8")


def test_materialize_main_materializes_skill_daily_record(tmp_path: Path, monkeypatch):
    db_path = seed_document_with_candidate(tmp_path)
    vault_dir = tmp_path / "vault"
    candidate_dir = vault_dir / "60_Inbox" / "Candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO knowledge_records
                (id, record_type, title, content, agent_type, recorded_at,
                 candidate_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "kr_skill_daily",
                "daily",
                "当天补充事项",
                "把知识记录路径纳入日常复盘。",
                "codex",
                now,
                "2026-07-04",
                "accepted",
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(materialize_candidates, "OBSIDIAN_VAULT_DIR", vault_dir)
    monkeypatch.setattr(materialize_candidates, "CANDIDATE_DIR", candidate_dir)
    monkeypatch.setattr(materialize_candidates, "get_db_connection", lambda: source_ingest_store.get_db_connection(db_path))
    monkeypatch.setattr(materialize_candidates, "sys", SimpleNamespace(argv=["materialize_candidates.py", "2026-07-04"]))

    materialize_candidates.main()

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        row = conn.execute(
            "SELECT materialized_path FROM knowledge_records WHERE id = ?",
            ("kr_skill_daily",),
        ).fetchone()
    finally:
        conn.close()

    assert row["materialized_path"] == "10_Periodic/Daily/2026-07-04.md"
    daily_path = vault_dir / row["materialized_path"]
    assert "knowledge_candidate:kr_skill_daily" in daily_path.read_text(encoding="utf-8")
