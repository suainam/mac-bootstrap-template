from __future__ import annotations

import sys
from pathlib import Path

DATA_HUB_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import daily_summary
from data_hub_test_support import seed_message_and_source_data, temp_db_and_vault
from db_helper import get_db_connection, query_execution_log


def test_daily_summary_helpers_and_main(temp_db_and_vault, monkeypatch) -> None:
    db_path, vault_dir = temp_db_and_vault
    seed_message_and_source_data(db_path, vault_dir)

    daily_note = vault_dir / "10_Periodic" / "Daily" / "2026-07-08.md"
    daily_note.write_text("# 2026-07-08\n\n## AI 总结\n\n旧总结\n", encoding="utf-8")
    monkeypatch.setenv("USER", "someone")
    monkeypatch.setattr(daily_summary, "DAILY_DIR", daily_note.parent)

    agent_digest = daily_summary.get_agent_logs_from_db("2026-07-08")
    source_digest = daily_summary.get_external_source_digest("2026-07-08")
    candidate_digest = daily_summary.get_candidate_digest("2026-07-08")

    assert agent_digest.count("请复用 growth 实验结论") == 1
    assert "Codex (growth)" in agent_digest
    assert "wiki_page | 增长方案" in source_digest
    assert "采用 filename_first" in candidate_digest

    monkeypatch.setattr(daily_summary, "get_git_logs", lambda _: ["**repo**\n- abc123 change"])
    monkeypatch.setattr(daily_summary, "generate_summary", lambda _: "## AI 总结\n- 汇总完成")
    monkeypatch.setattr(sys, "argv", ["daily_summary.py", "2026-07-08"])

    daily_summary.main()

    text = daily_note.read_text(encoding="utf-8")
    assert "汇总完成" in text
    assert "旧总结" not in text

    conn = get_db_connection()
    try:
        logs = query_execution_log(conn, "2026-07-08")
    finally:
        conn.close()
    assert any(log["step_name"] == "daily_summary" and log["status"] == "completed" for log in logs)


def test_daily_summary_generate_summary_and_failure_logging(temp_db_and_vault, monkeypatch) -> None:
    _db_path, vault_dir = temp_db_and_vault
    daily_note = vault_dir / "10_Periodic" / "Daily" / "2026-07-09.md"
    daily_note.write_text("# 2026-07-09\n\n## AI 总结\n\n旧总结\n", encoding="utf-8")
    monkeypatch.setattr(daily_summary, "DAILY_DIR", daily_note.parent)

    monkeypatch.setattr(daily_summary, "call_llm_raw", lambda p: "llm result")
    assert daily_summary.generate_summary("prompt") == "llm result"

    monkeypatch.setattr(daily_summary, "call_llm_raw", lambda p: "")
    assert daily_summary.generate_summary("prompt") == "调用 LLM 失败，未能生成总结。"

    monkeypatch.setattr(daily_summary, "get_git_logs", lambda _: [])
    monkeypatch.setattr(daily_summary, "get_agent_logs_from_db", lambda _: "")
    monkeypatch.setattr(daily_summary, "get_external_source_digest", lambda _: "")
    monkeypatch.setattr(daily_summary, "get_candidate_digest", lambda _: "")
    monkeypatch.setattr(daily_summary, "generate_summary", lambda _: "调用 LLM 失败，未能生成总结。")
    monkeypatch.setattr(sys, "argv", ["daily_summary.py", "2026-07-09"])

    daily_summary.main()

    conn = get_db_connection()
    try:
        logs = query_execution_log(conn, "2026-07-09")
    finally:
        conn.close()
    assert any(log["step_name"] == "daily_summary" and log["status"] == "failed" for log in logs)


def test_daily_summary_creates_missing_daily_note(temp_db_and_vault, monkeypatch) -> None:
    db_path, vault_dir = temp_db_and_vault
    seed_message_and_source_data(db_path, vault_dir)

    daily_note = vault_dir / "10_Periodic" / "Daily" / "2026-07-10.md"
    monkeypatch.setenv("USER", "someone")
    monkeypatch.setattr(daily_summary, "DAILY_DIR", daily_note.parent)
    monkeypatch.setattr(daily_summary, "get_git_logs", lambda _: [])
    monkeypatch.setattr(daily_summary, "get_agent_logs_from_db", lambda _: "")
    monkeypatch.setattr(daily_summary, "get_external_source_digest", lambda _: "")
    monkeypatch.setattr(daily_summary, "get_candidate_digest", lambda _: "")
    monkeypatch.setattr(daily_summary, "generate_summary", lambda _: "- 自动创建日报后写入总结")
    monkeypatch.setattr(sys, "argv", ["daily_summary.py", "2026-07-10"])

    daily_summary.main()

    text = daily_note.read_text(encoding="utf-8")
    assert "## AI 总结" in text
    assert "自动创建日报后写入总结" in text

    conn = get_db_connection()
    try:
        logs = query_execution_log(conn, "2026-07-10")
    finally:
        conn.close()
    assert any(log["step_name"] == "daily_summary" and log["status"] == "completed" for log in logs)


def test_get_agent_logs_from_db_uses_local_date_for_utc_timestamps(temp_db_and_vault, monkeypatch) -> None:
    db_path, _vault_dir = temp_db_and_vault
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO sessions (id, agent_type, project_path, start_time, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("utc-session", "codex", "Workspace", "2026-07-04T16:06:53Z", "2026-07-04T16:06:53Z"),
        )
        conn.execute(
            "INSERT INTO messages (session_id, timestamp, role, content) VALUES (?, ?, ?, ?)",
            ("utc-session", "2026-07-04T16:06:53Z", "user", "这条消息在本地时区属于 2026-07-05"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("AGENT_DB_PATH", str(db_path))

    digest = daily_summary.get_agent_logs_from_db("2026-07-05")

    assert "这条消息在本地时区属于 2026-07-05" in digest


def test_build_summary_prompt_uses_langgpt_structure() -> None:
    prompt = daily_summary.build_summary_prompt(
        git_digest="test git",
        agent_digest="test agent",
        source_digest="test source",
        candidate_digest="test candidate",
    )
    assert "# Role" in prompt
    assert "## Profile" in prompt
    assert "## Skills" in prompt
    assert "## Rules" in prompt
    assert "## OutputFormat" in prompt
    assert "## Input Data" in prompt


def test_daily_summary_prompt_requires_specific_hierarchical_tags() -> None:
    prompt = daily_summary.build_summary_prompt(
        git_digest="**repo**\n- ship data hub acceptance",
        agent_digest="完成 pipeline 验收并记录上下游风险",
        source_digest="无",
        candidate_digest="无",
    )

    assert "#绩效-计划组织" in prompt
    assert "#复盘-做得好" in prompt
    assert "禁止使用 `#绩效`、`#成长`、`#复盘` 这类只有一级的粗标签" in prompt


def test_daily_summary_sanitizes_and_normalizes_summary_tags() -> None:
    summary = "- 完成验收。 #绩效 #复盘\n- 产出报告。 `#绩效/计划组织` `#复盘/做得好`"

    sanitized = daily_summary.sanitize_summary_tags(summary)

    assert "#绩效 " not in f"{sanitized} "
    assert "#复盘\n" not in f"{sanitized}\n"
    assert "#绩效-计划组织" in sanitized
    assert "#复盘-做得好" in sanitized
    assert "`#绩效-计划组织`" not in sanitized


def test_generate_summary_delegates_to_call_llm_raw(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(daily_summary, "call_llm_raw", lambda p: calls.append(p) or "mocked summary", raising=False)
    result = daily_summary.generate_summary("my prompt")
    assert calls == ["my prompt"]
    assert result == "mocked summary"
