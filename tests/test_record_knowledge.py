from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import pytest


SCRIPTS_DIR = (
    Path(__file__).parent.parent
    / "agent" / "skills" / "personal" / "knowledge-record" / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR.resolve()))

import record_knowledge


SCHEMA_SQL = (SCRIPTS_DIR.parents[3] / "data-hub" / "schema.sql").read_text()


def make_conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def make_args(**kwargs) -> argparse.Namespace:
    base = {
        "type": "adr",
        "title": "测试知识",
        "content": "这是一条测试知识记录。",
        "background": "这是这条架构决策的上下文。",
        "tags": "知识记录,架构决策",
        "impact": None,
        "is_actionable": False,
        "references": "docs/adr.md",
        "project": None,
        "expires_at": None,
        "why_record": "需要保留这次决策，供后续复用。",
        "agent": "codex",
        "session_id": None,
        "message_id": None,
        "project_path": None,
        "date": None,
        "db_path": None,
        "dry_run": False,
        "no_vault_init": False,
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


class TestBuildRecord:
    def test_basic_record(self):
        args = make_args()
        record = record_knowledge.build_record(args)
        assert record["record_type"] == "adr"
        assert record["title"] == "测试知识"
        assert record["content"] == "这是一条测试知识记录。"
        assert record["status"] == "accepted"
        assert record["id"].startswith("kr-")
        assert len(record["id"]) == 19

    def test_tags_parsed(self):
        args = make_args(tags="架构决策,性能优化")
        record = record_knowledge.build_record(args)
        assert record["tags"] == "架构决策,性能优化"

    def test_tags_whitespace(self):
        args = make_args(tags=" 架构决策 , 性能优化 ")
        record = record_knowledge.build_record(args)
        assert record["tags"] == "架构决策,性能优化"

    def test_tags_deduplicated(self):
        args = make_args(tags="架构决策,性能优化,架构决策")
        record = record_knowledge.build_record(args)
        assert record["tags"] == "架构决策,性能优化"

    def test_rejects_empty_tags(self):
        args = make_args(tags=None)
        with pytest.raises(ValueError, match="tags are required"):
            record_knowledge.build_record(args)

    def test_rejects_non_chinese_tag(self):
        args = make_args(tags="架构决策,Rust")
        with pytest.raises(ValueError, match="tags must be non-empty Chinese labels"):
            record_knowledge.build_record(args)

    def test_rejects_invalid_agent_type(self):
        args = make_args(agent="cursor")
        with pytest.raises(ValueError, match="agent_type must be one of"):
            record_knowledge.build_record(args)

    def test_accepts_opencode_agent_type(self):
        args = make_args(agent="opencode")
        record = record_knowledge.build_record(args)
        assert record["agent_type"] == "opencode"

    def test_rejects_missing_agent_type(self, monkeypatch):
        monkeypatch.delenv("OPENCODE_AGENT", raising=False)
        monkeypatch.delenv("CODEX_AGENT", raising=False)
        args = make_args(agent=None)
        with pytest.raises(ValueError, match="agent_type is required"):
            record_knowledge.build_record(args)

    def test_rejects_non_chinese_dominant_title(self):
        args = make_args(title="Install Coze Desktop")
        with pytest.raises(ValueError, match="title must be Chinese-dominant"):
            record_knowledge.build_record(args)

    def test_rejects_non_chinese_dominant_content(self):
        args = make_args(content="Install the application and save the dmg.")
        with pytest.raises(ValueError, match="content must be Chinese-dominant"):
            record_knowledge.build_record(args)

    def test_adr_requires_background_references_and_why_record(self):
        args = make_args(background=None)
        with pytest.raises(ValueError, match="background is required"):
            record_knowledge.build_record(args)

        args = make_args(references=None)
        with pytest.raises(ValueError, match="references are required for adr"):
            record_knowledge.build_record(args)

        args = make_args(why_record=None)
        with pytest.raises(ValueError, match="why_record is required"):
            record_knowledge.build_record(args)

    def test_card_requires_why_record_only(self):
        args = make_args(
            type="card",
            background=None,
            references=None,
            why_record="需要记录这个工具安装结论。",
        )
        record = record_knowledge.build_record(args)
        assert record["background"] is None
        assert record["references_json"] is None

        args = make_args(type="card", why_record=None)
        with pytest.raises(ValueError, match="why_record is required"):
            record_knowledge.build_record(args)

    def test_daily_requires_why_record_only(self):
        args = make_args(
            type="daily",
            background=None,
            references=None,
            why_record="需要保留今天的关键工作记录。",
        )
        record = record_knowledge.build_record(args)
        assert record["background"] is None
        assert record["references_json"] is None

    def test_impact(self):
        args = make_args(impact="high")
        record = record_knowledge.build_record(args)
        assert record["impact"] == "high"

    def test_is_actionable(self):
        args = make_args(is_actionable=True)
        record = record_knowledge.build_record(args)
        assert record["is_actionable"] == 1

    def test_project_auto_detected(self):
        args = make_args(project_path="/tmp/work/my-project")
        record = record_knowledge.build_record(args)
        assert record["project"] == "my-project"

    def test_project_explicit(self):
        args = make_args(project="explicit-project")
        record = record_knowledge.build_record(args)
        assert record["project"] == "explicit-project"

    def test_date_default(self):
        from datetime import date
        args = make_args()
        record = record_knowledge.build_record(args)
        assert record["candidate_date"] == date.today().isoformat()

    def test_date_explicit(self):
        args = make_args(date="2026-07-04")
        record = record_knowledge.build_record(args)
        assert record["candidate_date"] == "2026-07-04"

    def test_record_id_deterministic(self):
        args = make_args()
        r1 = record_knowledge.build_record(args)
        r2 = record_knowledge.build_record(args)
        assert r1["id"] == r2["id"]

    def test_record_id_stable_across_retry_seconds(self):
        args = make_args()
        r1 = record_knowledge.build_record(args)
        time.sleep(1.01)
        r2 = record_knowledge.build_record(args)
        assert r1["id"] == r2["id"]

    def test_record_id_changes_with_content(self):
        args1 = make_args(content="内容甲")
        args2 = make_args(content="内容乙")
        r1 = record_knowledge.build_record(args1)
        r2 = record_knowledge.build_record(args2)
        assert r1["id"] != r2["id"]


class TestInsertRecord:
    def test_insert_and_retrieve(self, tmp_path):
        conn = make_conn(tmp_path)
        args = make_args()
        record = record_knowledge.build_record(args)
        record_id = record_knowledge.insert_record(conn, record)

        row = conn.execute(
            "SELECT id, record_type, title, status FROM knowledge_records WHERE id = ?",
            (record_id,),
        ).fetchone()
        assert row is not None
        assert row["record_type"] == "adr"
        assert row["title"] == "测试知识"
        assert row["status"] == "accepted"

        contract = conn.execute(
            """
            SELECT record_revision, authority, source_kind
            FROM knowledge_records
            WHERE id = ?
            """,
            (record_id,),
        ).fetchone()
        assert contract["record_revision"] == "kr-v1"
        assert contract["authority"] == "trusted_agent"
        assert contract["source_kind"] == "live_agent"

    def test_idempotent_insert(self, tmp_path):
        conn = make_conn(tmp_path)
        args = make_args()
        record = record_knowledge.build_record(args)

        id1 = record_knowledge.insert_record(conn, record)
        id2 = record_knowledge.insert_record(conn, record)

        assert id1 == id2
        rows = conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_records"
        ).fetchone()
        assert rows["cnt"] == 1

    def test_multiple_types(self, tmp_path):
        conn = make_conn(tmp_path)
        fixtures = [
            make_args(type="adr", title="架构决策记录"),
            make_args(
                type="card",
                title="知识卡片记录",
                background=None,
                references=None,
                why_record="需要保留这条知识卡片，供后续查询。",
            ),
            make_args(
                type="daily",
                title="每日日志记录",
                background=None,
                references=None,
                why_record="需要记录今天的关键进展。",
            ),
        ]
        for args in fixtures:
            record = record_knowledge.build_record(args)
            record_knowledge.insert_record(conn, record)

        rows = conn.execute(
            "SELECT record_type, title FROM knowledge_records ORDER BY record_type"
        ).fetchall()
        assert len(rows) == 3
        assert rows[0]["record_type"] == "adr"

    def test_full_field_set(self, tmp_path):
        conn = make_conn(tmp_path)
        args = make_args(
            type="card",
            title="完整字段测试",
            content="测试所有字段。",
            background="用户问怎么处理",
            tags="测试,字段",
            impact="medium",
            is_actionable=True,
            references="参考资料一,参考资料二",
            project="test-proj",
            expires_at="2026-12-31",
            why_record="这是一个端到端测试",
            agent="codex",
            session_id="sess-123",
            message_id=42,
            project_path="/tmp/proj",
        )
        record = record_knowledge.build_record(args)
        record_id = record_knowledge.insert_record(conn, record)

        row = conn.execute("SELECT * FROM knowledge_records WHERE id = ?", (record_id,)).fetchone()
        assert row["record_type"] == "card"
        assert row["tags"] == "测试,字段"
        assert row["impact"] == "medium"
        assert row["is_actionable"] == 1
        assert row["references_json"] == "参考资料一,参考资料二"
        assert row["project"] == "test-proj"
        assert row["expires_at"] == "2026-12-31"
        assert row["why_record"] == "这是一个端到端测试"
        assert row["agent_type"] == "codex"
        assert row["session_id"] == "sess-123"
        assert row["message_id"] == 42

    def test_schema_migration_does_not_upgrade_old_records(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "legacy.db"))
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE knowledge_records (
                id TEXT PRIMARY KEY,
                record_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                candidate_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'accepted',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO knowledge_records
                (id, record_type, title, content, agent_type, recorded_at, candidate_date, status, created_at, updated_at)
            VALUES
                ('kr-old', 'card', '旧记录', '旧内容', 'codex', '2026-07-01T00:00:00', '2026-07-01', 'accepted', '2026-07-01T00:00:00', '2026-07-01T00:00:00')
            """
        )
        conn.commit()

        record = record_knowledge.build_record(make_args(title="新记录", content="新内容", date="2026-07-01"))
        record_knowledge.insert_record(conn, record)

        old_row = conn.execute("SELECT record_revision FROM knowledge_records WHERE id = 'kr-old'").fetchone()
        new_row = conn.execute("SELECT record_revision FROM knowledge_records WHERE id = ?", (record["id"],)).fetchone()
        assert old_row["record_revision"] is None
        assert new_row["record_revision"] == "kr-v1"


def test_find_db_path_uses_runtime_config_from_repo_root(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    runtime_dir = repo / "private" / "agent"
    runtime_dir.mkdir(parents=True)
    expected_db = tmp_path / "runtime.db"
    (runtime_dir / "data_hub.runtime.jsonc").write_text(
        '{"paths": {"db_path": "%s"}}' % str(expected_db),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert record_knowledge.find_db_path() == expected_db


def test_find_db_path_expands_environment_variables(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    runtime_dir = repo / "private" / "agent"
    runtime_dir.mkdir(parents=True)
    expected_db = tmp_path / "home" / "work" / "config" / "mac-bootstrap" / "private" / "agent" / "data" / "agent_history.db"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (runtime_dir / "data_hub.runtime.jsonc").write_text(
        '{"paths": {"db_path": "$HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db"}}',
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert record_knowledge.find_db_path() == expected_db
