from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(SCRIPTS_DIR))

import ingest_logs
from data_hub_test_support import temp_db_and_vault
from db_helper import get_db_connection, query_execution_log, query_messages_count, query_sessions_count


def test_ingest_logs_end_to_end_and_main(temp_db_and_vault, monkeypatch, tmp_path) -> None:
    _db_path, _vault_dir = temp_db_and_vault
    claude_dir = tmp_path / "claude" / "projects" / "demo-project"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "session.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "claude-1",
                        "timestamp": "2026-07-08T10:00:00",
                        "sessionId": "claude-session",
                        "message": {"content": [{"type": "text", "text": "Hello <ADDITIONAL_METADATA>x</ADDITIONAL_METADATA> World"}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "claude-2",
                        "timestamp": "2026-07-08T10:01:00",
                        "sessionId": "claude-session",
                        "message": {"content": "System: context injected"},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    codex_dir = tmp_path / "codex" / "2026" / "07" / "08"
    codex_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "session.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-08T11:00:00",
                        "payload": {"role": "user", "content": [{"type": "input_text", "text": "整理 sqlite 方案"}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "message",
                        "timestamp": "2026-07-08T11:05:00",
                        "payload": {"role": "user", "content": "<skill>skip</skill>"},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    agy_dir = tmp_path / ".gemini" / "antigravity-cli" / "brain" / "sess-1" / ".system_generated" / "logs"
    agy_dir.mkdir(parents=True, exist_ok=True)
    (agy_dir / "transcript.jsonl").write_text(
        json.dumps({"type": "USER_INPUT", "created_at": "2026-07-08T12:00:00", "content": "<USER_REQUEST>总结 AGY 事项并输出行动列表</USER_REQUEST>"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(ingest_logs, "CLAUDE_PROJECTS_DIR", claude_dir.parent)
    monkeypatch.setattr(ingest_logs, "CODEX_SESSIONS_DIR", codex_dir.parents[2])
    monkeypatch.setattr(ingest_logs, "OPENCODE_SESSIONS_DIR", codex_dir.parents[2])
    monkeypatch.setenv("USER", "tester")

    conn = get_db_connection()
    try:
        assert ingest_logs.ingest_claude(conn) == 1
        assert ingest_logs.ingest_codex(conn) == 1
        monkeypatch.setattr(ingest_logs.Path, "home", staticmethod(lambda: tmp_path))
        assert ingest_logs.ingest_agy(conn) == 1
    finally:
        conn.close()

    conn = get_db_connection()
    try:
        assert query_sessions_count(conn) == 3
        assert query_messages_count(conn) == 3
        contents = [row["content"] for row in conn.execute("SELECT content FROM messages ORDER BY timestamp").fetchall()]
    finally:
        conn.close()
    assert contents == ["Hello  World", "整理 sqlite 方案", "总结 AGY 事项并输出行动列表"]

    monkeypatch.setattr(ingest_logs, "ingest_claude", lambda conn: 2)
    monkeypatch.setattr(ingest_logs, "ingest_codex", lambda conn: 3)
    monkeypatch.setattr(ingest_logs, "ingest_agy", lambda conn: 4)
    monkeypatch.setattr(sys, "argv", ["ingest_logs.py"])
    ingest_logs.main()

    conn = get_db_connection()
    try:
        logs = query_execution_log(conn, datetime.now().strftime("%Y-%m-%d"))
    finally:
        conn.close()
    assert any(log["step_name"] == "ingest_logs" and log["records_affected"] == 9 for log in logs)


def test_ingest_logs_missing_agent_dirs_return_zero(temp_db_and_vault, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ingest_logs, "CLAUDE_PROJECTS_DIR", tmp_path / "missing-claude")
    monkeypatch.setattr(ingest_logs, "CODEX_SESSIONS_DIR", tmp_path / "missing-codex")
    monkeypatch.setattr(ingest_logs.Path, "home", staticmethod(lambda: tmp_path / "missing-home"))

    conn = get_db_connection()
    try:
        assert ingest_logs.ingest_claude(conn) == 0
        assert ingest_logs.ingest_codex(conn) == 0
        assert ingest_logs.ingest_agy(conn) == 0
    finally:
        conn.close()


def test_ingest_agy_skips_malformed_jsonl_lines(temp_db_and_vault, monkeypatch, tmp_path, capsys) -> None:
    agy_dir = tmp_path / ".gemini" / "antigravity-cli" / "brain" / "sess-bad" / ".system_generated" / "logs"
    agy_dir.mkdir(parents=True, exist_ok=True)
    (agy_dir / "transcript.jsonl").write_text(
        "\n".join(
            [
                '{"type": "USER_INPUT", "created_at": "2026-07-08T12:00:00", "content": "<USER_REQUEST>保留这条有效 AGY 输入用于验收</USER_REQUEST>"}',
                '{"type": "USER_INPUT", ',
                'not-json',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ingest_logs.Path, "home", staticmethod(lambda: tmp_path))

    conn = get_db_connection()
    try:
        assert ingest_logs.ingest_agy(conn) == 1
    finally:
        conn.close()

    captured = capsys.readouterr()
    assert "Error parsing AGY file" not in captured.out
    assert "skipped 2 malformed AGY json lines" in captured.out

    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT content FROM messages WHERE session_id = 'sess-bad'").fetchall()
    finally:
        conn.close()
    assert [row["content"] for row in rows] == ["保留这条有效 AGY 输入用于验收"]
