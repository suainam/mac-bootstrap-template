import sys
from datetime import datetime
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(SCRIPTS_DIR))

import claim_extraction
import hygiene_audit
import knowledge_retrieval
import knowledge_workflows
import source_ingest_store
from source_adapters.common import Chunk, Item


def seed_knowledge_db(db_path: Path, vault_dir: Path) -> None:
    conn = source_ingest_store.get_db_connection(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    try:
        source_path = vault_dir / "50_Sources" / "Meetings" / "2026-07-04_growth-review.md"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text("决定采用 filename_first。\n待办\n· 跟进门店实验@南宗帅\n", encoding="utf-8")
        doc_id = source_ingest_store.upsert_document(
            conn,
            "meeting_note",
            source_path,
            "增长复盘",
            "hash-growth",
            {"filename_date": "2026-07-04", "landing_date": "2026-07-04"},
        )
        chunk_ids = source_ingest_store.insert_chunks(
            conn,
            doc_id,
            [
                Chunk(chunk_type="paragraph", locator="p1", content="决定采用 filename_first。", metadata={}),
                Chunk(chunk_type="bullet", locator="p2", content="· 跟进门店实验@南宗帅", metadata={}),
            ],
        )
        source_ingest_store.insert_items(
            conn,
            doc_id,
            chunk_ids,
            [
                Item(item_type="decision", title="采用 filename_first", content="默认按文件名日期归因。", confidence=0.92, chunk_index=0, metadata={}),
                Item(item_type="action", title="跟进门店实验", content="联系运营确认实验窗口。", confidence=0.89, chunk_index=1, metadata={}),
            ],
        )

        extracted_ids = conn.execute(
            "SELECT id FROM extracted_items WHERE document_id = ? ORDER BY rowid ASC",
            (doc_id,),
        ).fetchall()
        conn.execute(
            "INSERT INTO sessions (id, agent_type, project_path, start_time, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("session_demo", "codex", "Workspace", now, now),
        )
        conn.execute(
            "INSERT INTO messages (session_id, timestamp, role, content) VALUES (?, ?, ?, ?)",
            ("session_demo", "2026-07-04T09:00:00", "user", "如何复用之前的增长实验结论？"),
        )
        conn.execute(
            """
            INSERT INTO knowledge_candidates
                (id, extracted_item_id, source_document_id, candidate_date, candidate_type, status,
                 title, content, confidence, metadata_json, materialized_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cand_open_loop",
                extracted_ids[1][0],
                doc_id,
                "2026-07-04",
                "daily",
                "pending",
                "跟进 growth 门店实验",
                "联系运营确认 growth 实验窗口。",
                0.89,
                '{"source_type":"meeting_note","document_title":"增长复盘","project":"growth"}',
                None,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def seed_knowledge_notes(vault_dir: Path) -> None:
    (vault_dir / "10_Periodic" / "Daily").mkdir(parents=True, exist_ok=True)
    (vault_dir / "40_Knowledge" / "ADR").mkdir(parents=True, exist_ok=True)
    (vault_dir / "40_Knowledge" / "Cards").mkdir(parents=True, exist_ok=True)

    (vault_dir / "10_Periodic" / "Daily" / "2026-07-04.md").write_text(
        "# 2026-07-04\n\n- 跟进 growth 实验和 filename_first。\n",
        encoding="utf-8",
    )
    (vault_dir / "40_Knowledge" / "ADR" / "2026-07-04-filename-first.md").write_text(
        "---\ncandidate_id: cand_demo\nproject: growth\n---\n\n# 采用 filename_first\n",
        encoding="utf-8",
    )
    (vault_dir / "40_Knowledge" / "Cards" / "2026-07-04-growth-card.md").write_text(
        "# 增长实验复用\n\n在 growth 实验里优先复用既有结论。\n",
        encoding="utf-8",
    )


def test_build_retrieval_packet_returns_structured_hits(tmp_path: Path, monkeypatch):
    vault_dir = tmp_path / "vault"
    db_path = tmp_path / "agent_history.db"
    seed_knowledge_notes(vault_dir)
    seed_knowledge_db(db_path, vault_dir)

    monkeypatch.setattr(knowledge_retrieval, "OBSIDIAN_VAULT_DIR", vault_dir)
    monkeypatch.setattr(knowledge_retrieval, "DB_PATH", db_path)

    packet = knowledge_retrieval.build_retrieval_packet(
        task_goal="复用增长实验知识",
        keywords=["growth", "filename_first"],
        project="growth",
        date_from="2026-07-04",
        date_to="2026-07-04",
    )

    assert packet["matched_daily"]
    assert packet["matched_adrs"]
    assert packet["matched_cards"]
    assert packet["open_loops"][0]["candidate_id"] == "cand_open_loop"
    assert packet["reuse_recommendations"]


def test_build_claim_packet_and_hygiene_report(tmp_path: Path, monkeypatch):
    vault_dir = tmp_path / "vault"
    db_path = tmp_path / "agent_history.db"
    seed_knowledge_notes(vault_dir)
    seed_knowledge_db(db_path, vault_dir)

    monkeypatch.setattr(claim_extraction, "DB_PATH", db_path)
    packet = claim_extraction.build_claim_packet("2026-07-04", include_chat=True)

    claim_types = {claim["claim_type"] for claim in packet["claim_packets"]}
    assert "decision" in claim_types
    assert "action" in claim_types
    assert "open_loop" in claim_types
    assert packet["evidence_links"]
    assert packet["promotion_suggestions"]

    monkeypatch.setattr(hygiene_audit, "DB_PATH", db_path)
    monkeypatch.setattr(hygiene_audit, "OBSIDIAN_VAULT_DIR", vault_dir)
    report = hygiene_audit.build_audit_report("2026-07-05")

    assert report["stale_review_items"][0]["id"] == "cand_open_loop"
    assert report["repair_recommendations"]


def test_daily_workflows_define_and_run_expected_steps():
    ingest_steps = knowledge_workflows.build_workflow_steps("daily_ingest_and_review", "2026-07-04")
    promote_steps = knowledge_workflows.build_workflow_steps("daily_promote_and_summary", "2026-07-04")
    full_cycle_steps = knowledge_workflows.build_workflow_steps("full_cycle", "2026-07-04")
    review_only_steps = knowledge_workflows.build_workflow_steps("auto_review_only", "2026-07-04")
    materialize_only_steps = knowledge_workflows.build_workflow_steps("materialize_only", "2026-07-04")

    assert [step["name"] for step in ingest_steps] == [
        "knowledge-reuse-retrieval",
        "knowledge-source-ingestion:logs",
        "knowledge-source-ingestion:sources",
        "knowledge-claim-extraction",
        "knowledge-candidate-review",
    ]
    assert [step["name"] for step in promote_steps] == [
        "knowledge-materialization",
        "knowledge-daily-weekly-synthesis",
    ]
    assert [step["name"] for step in review_only_steps] == ["knowledge-auto-review"]
    assert [step["name"] for step in materialize_only_steps] == ["knowledge-materialization"]
    assert [step["name"] for step in full_cycle_steps] == [
        "knowledge-reuse-retrieval",
        "knowledge-source-ingestion:logs",
        "knowledge-source-ingestion:sources",
        "knowledge-claim-extraction",
        "knowledge-candidate-review",
        "knowledge-auto-review",
        "knowledge-materialization",
        "knowledge-daily-weekly-synthesis",
    ]

    seen = []

    def fake_runner(command, check):
        assert check is True
        seen.append(command)

    result = knowledge_workflows.run_workflow(
        "daily_promote_and_summary",
        "2026-07-04",
        runner=fake_runner,
    )

    assert len(seen) == 2
    assert [item["name"] for item in result] == ["knowledge-materialization", "knowledge-daily-weekly-synthesis"]


def test_source_adapter_upgrade_uses_template_test_path():
    steps = knowledge_workflows.build_workflow_steps("source_adapter_upgrade", "2026-07-04")

    pytest_step = steps[1]["command"]
    assert pytest_step[-2].endswith("test_data_hub_sources.py")
    assert Path(pytest_step[-2]).is_absolute()
