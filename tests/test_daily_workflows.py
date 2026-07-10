import sys
import subprocess
from datetime import datetime
from pathlib import Path

import pytest


DATA_HUB_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import claim_extraction
import hygiene_audit
import knowledge_retrieval
import knowledge_workflows
import source_ingest_store
from workflow_contracts import StageSpec, SuccessCheck
from source_adapters.common import Chunk, Item


def seed_knowledge_db(db_path: Path, vault_dir: Path) -> None:
    conn = source_ingest_store.get_db_connection(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    try:
        source_path = vault_dir / "raw" / "sources" / "Meetings" / "2026-07-04_growth-review.md"
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
                Chunk(chunk_type="paragraph", locator="p3", content="开放问题：如何复用之前的增长实验结论？", metadata={}),
            ],
        )
        source_ingest_store.insert_items(
            conn,
            doc_id,
            chunk_ids,
            [
                Item(
                    item_type="decision",
                    title="采用 filename_first",
                    content="默认按文件名日期归因。",
                    confidence=0.92,
                    chunk_index=0,
                    metadata={},
                ),
                Item(
                    item_type="action",
                    title="跟进门店实验",
                    content="联系运营确认实验窗口。",
                    confidence=0.89,
                    chunk_index=1,
                    metadata={},
                ),
                Item(
                    item_type="open_loop",
                    title="复用增长实验结论",
                    content="如何复用之前的增长实验结论？",
                    confidence=0.72,
                    chunk_index=2,
                    metadata={},
                ),
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
    steps = knowledge_workflows.build_workflow_steps("build_daily_summary", "2026-07-04")
    assert [step.name for step in steps] == ["build-daily-summary"]

    seen = []

    def fake_runner(command, check):
        assert check is True
        seen.append(command)

    result = knowledge_workflows.run_workflow(
        "build_daily_summary",
        "2026-07-04",
        runner=fake_runner,
    )

    assert len(seen) == 1
    assert [item["name"] for item in result] == ["build-daily-summary"]


def test_daily_workflow_dry_run_returns_json_ready_contracts():
    result = knowledge_workflows.run_workflow("build_daily_summary", "2026-07-04", dry_run=True)

    assert result[0]["name"] == "build-daily-summary"
    assert result[0]["produces"] == ["70_Summaries/Daily/"]


def test_supported_workflows_use_summary_pipeline_not_full_cycle():
    assert knowledge_workflows.supported_workflows() == [
        "build_daily_summary",
        "build_weekly_summary",
        "build_monthly_summary",
        "build_quarterly_summary",
        "build_yearly_summary",
    ]


def test_period_summary_workflow_uses_internal_builder():
    steps = knowledge_workflows.build_workflow_steps("build_weekly_summary", "2026-07-09")

    assert len(steps) == 1
    assert steps[0].name == "build-weekly-summary"
    assert "build_period_summary.py" in steps[0].command[1]
    assert steps[0].command[-4:] == ["--level", "weekly", "--anchor-date", "2026-07-09"]
    assert steps[0].produces == ["70_Summaries/Weekly/"]


def test_daily_summary_workflow_uses_period_builder():
    steps = knowledge_workflows.build_workflow_steps("build_daily_summary", "2026-07-10")

    assert len(steps) == 1
    assert steps[0].name == "build-daily-summary"
    assert "build_period_summary.py" in steps[0].command[1]
    assert steps[0].command[-4:] == ["--level", "daily", "--anchor-date", "2026-07-10"]
    assert steps[0].produces == ["70_Summaries/Daily/"]


def test_durable_workflow_records_failure_and_logs(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "agent_history.db"
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    calls = []

    def fake_command_runner(command, cwd, capture_output, text):
        calls.append(command)
        assert cwd == knowledge_workflows.CURRENT_DIR
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(command, 7, stdout="partial output", stderr="boom")

    results = knowledge_workflows.run_durable_workflow(
        "build_daily_summary",
        "2026-07-04",
        run_id="run_test_failure",
        command_runner=fake_command_runner,
        runs_dir=tmp_path / "runs",
        max_attempts=1,
    )

    assert results[0]["status"] == "failed"
    assert Path(results[0]["stdout_path"]).read_text(encoding="utf-8") == "partial output"
    assert Path(results[0]["stderr_path"]).read_text(encoding="utf-8") == "boom"

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        run = conn.execute(
            "SELECT status, error_message FROM workflow_runs WHERE id = ?",
            ("run_test_failure",),
        ).fetchone()
        step = conn.execute(
            "SELECT status, attempt, exit_code FROM workflow_steps WHERE run_id = ?",
            ("run_test_failure",),
        ).fetchone()
        artifacts = conn.execute(
            "SELECT COUNT(*) FROM artifact_manifest WHERE run_id = ?",
            ("run_test_failure",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert run["status"] == "failed"
    assert "boom" in run["error_message"]
    assert dict(step) == {"status": "failed", "attempt": 1, "exit_code": 7}
    assert artifacts == 2


def test_durable_runner_executes_stage_spec(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "agent_history.db"
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))

    def fake_command_runner(command, cwd, capture_output, text):
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    results = knowledge_workflows.run_durable_workflow(
        "build_daily_summary",
        "2026-07-04",
        run_id="run_stage_spec",
        command_runner=fake_command_runner,
        runs_dir=tmp_path / "runs",
    )

    assert results[0]["status"] == "completed"


def test_durable_runner_fails_when_success_check_fails(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "agent_history.db"
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    stage = StageSpec(
        name="requires-file",
        command=["python", "noop.py"],
        success_checks=[SuccessCheck("file_exists", "10_Periodic/Daily/2026-07-04.md")],
    )

    def fake_command_runner(command, cwd, capture_output, text):
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    with knowledge_workflows.WorkflowRunner(command_runner=fake_command_runner, runs_dir=runs_dir) as runner:
        results = runner.run("custom", "2026-07-04", [stage], run_id="run_check_failed")

    assert results[0]["status"] == "failed"
    assert "expected file exists" in results[0]["error_message"]

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        run = conn.execute(
            "SELECT status, error_message FROM workflow_runs WHERE id = ?",
            ("run_check_failed",),
        ).fetchone()
        step = conn.execute(
            "SELECT status, exit_code, error_message FROM workflow_steps WHERE run_id = ?",
            ("run_check_failed",),
        ).fetchone()
    finally:
        conn.close()

    assert run["status"] == "failed"
    assert "expected file exists" in run["error_message"]
    assert dict(step) == {"status": "failed", "exit_code": 0, "error_message": results[0]["error_message"]}


def test_durable_runner_records_command_exception_as_failed(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "agent_history.db"
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    stage = StageSpec(name="raises", command=["missing-command"])

    def fake_command_runner(command, cwd, capture_output, text):
        raise FileNotFoundError("missing-command")

    with knowledge_workflows.WorkflowRunner(command_runner=fake_command_runner, runs_dir=tmp_path / "runs") as runner:
        results = runner.run("custom", "2026-07-04", [stage], run_id="run_exception")

    assert results[0]["status"] == "failed"
    assert "missing-command" in results[0]["error_message"]
    assert Path(results[0]["stderr_path"]).read_text(encoding="utf-8") == "missing-command"

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        run = conn.execute(
            "SELECT status, error_message FROM workflow_runs WHERE id = ?",
            ("run_exception",),
        ).fetchone()
        step = conn.execute(
            "SELECT status, exit_code, error_message FROM workflow_steps WHERE run_id = ?",
            ("run_exception",),
        ).fetchone()
    finally:
        conn.close()

    assert run["status"] == "failed"
    assert dict(step) == {"status": "failed", "exit_code": -1, "error_message": "missing-command"}


def test_durable_runner_rejects_conflicting_run_modes(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "agent_history.db"
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    stage = StageSpec(name="noop", command=["python", "noop.py"])

    with knowledge_workflows.WorkflowRunner(runs_dir=tmp_path / "runs") as runner:
        with pytest.raises(ValueError, match="mutually exclusive"):
            runner.run("custom", "2026-07-04", [stage], run_id="new", resume_run_id="old")


def test_durable_runner_marks_degraded_stage_and_run(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "agent_history.db"
    vault_dir = tmp_path / "vault"
    daily_note = vault_dir / "10_Periodic" / "Daily" / "2026-07-04.md"
    daily_note.parent.mkdir(parents=True, exist_ok=True)
    daily_note.write_text("# 2026-07-04\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("OBSIDIAN_VAULT_DIR", str(vault_dir))

    def fake_command_runner(command, cwd, capture_output, text):
        return subprocess.CompletedProcess(command, 0, stdout="SUMMARY_STATUS=degraded", stderr="")

    runner = knowledge_workflows.WorkflowRunner(command_runner=fake_command_runner, runs_dir=tmp_path / "runs")
    results = runner.run(
        "custom",
        "2026-07-04",
        knowledge_workflows.build_workflow_steps("build_daily_summary", "2026-07-04"),
        run_id="run_degraded",
    )

    assert results[0]["status"] == "degraded"
    assert "SUMMARY_STATUS=degraded" in results[0]["error_message"]

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        run_status = conn.execute(
            "SELECT status FROM workflow_runs WHERE id = ?",
            ("run_degraded",),
        ).fetchone()[0]
        step_status = conn.execute(
            "SELECT status FROM workflow_steps WHERE run_id = ?",
            ("run_degraded",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert run_status == "degraded"
    assert step_status == "degraded"


def test_durable_runner_resume_preserves_degraded_run_status(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "agent_history.db"
    vault_dir = tmp_path / "vault"
    daily_note = vault_dir / "10_Periodic" / "Daily" / "2026-07-04.md"
    daily_note.parent.mkdir(parents=True, exist_ok=True)
    daily_note.write_text("# 2026-07-04\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("OBSIDIAN_VAULT_DIR", str(vault_dir))

    def first_runner(command, cwd, capture_output, text):
        return subprocess.CompletedProcess(command, 0, stdout="SUMMARY_STATUS=degraded", stderr="")

    stage = knowledge_workflows.build_workflow_steps("build_daily_summary", "2026-07-04")[0]
    with knowledge_workflows.WorkflowRunner(command_runner=first_runner, runs_dir=tmp_path / "runs") as runner:
        first = runner.run("custom", "2026-07-04", [stage], run_id="run_resume_degraded")

    assert first[0]["status"] == "degraded"

    def second_runner(command, cwd, capture_output, text):
        raise AssertionError("resume should skip degraded completed step")

    with knowledge_workflows.WorkflowRunner(command_runner=second_runner, runs_dir=tmp_path / "runs") as runner:
        second = runner.run("custom", "2026-07-04", [stage], resume_run_id="run_resume_degraded")

    assert second == [
        {
            "name": "build-daily-summary",
            "status": "skipped",
            "run_id": "run_resume_degraded",
        }
    ]

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        run_status = conn.execute(
            "SELECT status FROM workflow_runs WHERE id = ?",
            ("run_resume_degraded",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert run_status == "degraded"


def test_durable_runner_from_step_reruns_completed_step(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "agent_history.db"
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    stage = StageSpec(name="rerunnable", command=["python", "noop.py"])
    calls = []

    def first_runner(command, cwd, capture_output, text):
        calls.append("first")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    with knowledge_workflows.WorkflowRunner(command_runner=first_runner, runs_dir=tmp_path / "runs") as runner:
        first = runner.run("custom", "2026-07-04", [stage], run_id="run_from_step")

    assert first[0]["status"] == "completed"

    def second_runner(command, cwd, capture_output, text):
        calls.append("second")
        return subprocess.CompletedProcess(command, 0, stdout="rerun", stderr="")

    with knowledge_workflows.WorkflowRunner(command_runner=second_runner, runs_dir=tmp_path / "runs") as runner:
        second = runner.run(
            "custom",
            "2026-07-04",
            [stage],
            resume_run_id="run_from_step",
            from_step="rerunnable",
        )

    assert [item["status"] for item in second] == ["completed"]
    assert calls == ["first", "second"]


def test_durable_workflow_retry_failed_resumes_from_failed_step(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "agent_history.db"
    vault_dir = tmp_path / "vault"
    daily_note = vault_dir / "10_Periodic" / "Daily" / "2026-07-04.md"
    daily_note.parent.mkdir(parents=True, exist_ok=True)
    daily_note.write_text("# 2026-07-04\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("OBSIDIAN_VAULT_DIR", str(vault_dir))
    call_count = 0

    def first_runner(command, cwd, capture_output, text):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="failed second")

    stages = [
        StageSpec(name="first", command=["python", "first.py"]),
        StageSpec(name="second", command=["python", "second.py"]),
    ]
    with knowledge_workflows.WorkflowRunner(command_runner=first_runner, runs_dir=tmp_path / "runs") as runner:
        first = runner.run("custom", "2026-07-04", stages, run_id="run_retry", max_attempts=1)
    assert [item["status"] for item in first] == ["completed", "failed"]

    retry_calls = []

    def retry_runner(command, cwd, capture_output, text):
        retry_calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="recovered", stderr="")

    with knowledge_workflows.WorkflowRunner(command_runner=retry_runner, runs_dir=tmp_path / "runs") as runner:
        second = runner.run("custom", "2026-07-04", stages, retry_failed_run_id="run_retry", max_attempts=1)

    assert [item["status"] for item in second] == ["skipped", "completed"]
    assert len(retry_calls) == 1

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        run_status = conn.execute("SELECT status FROM workflow_runs WHERE id = ?", ("run_retry",)).fetchone()[0]
        step_statuses = [
            row[0]
            for row in conn.execute(
                "SELECT status FROM workflow_steps WHERE run_id = ? ORDER BY step_index",
                ("run_retry",),
            ).fetchall()
        ]
    finally:
        conn.close()

    assert run_status == "completed"
    assert step_statuses == ["completed", "completed"]
