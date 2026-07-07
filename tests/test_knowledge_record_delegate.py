from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from lifecycle_manager_test_support import load_manager_module


def make_record_args(**kwargs) -> Namespace:
    base = {
        "record_type": "adr",
        "title": "知识记录标题",
        "content": "这是用于验证委托链路的中文内容。",
        "background": "这是这次记录的背景信息。",
        "tags": "知识记录,委托测试",
        "impact": "high",
        "references": "docs/ref.md",
        "project": "mac-bootstrap",
        "expires_at": "2026-07-31",
        "why_record": "需要验证 lifecycle manager 只做委托。",
        "agent": "codex",
        "session_id": "session-123",
        "message_id": 42,
        "project_path": "/tmp/project",
        "db_path": "/tmp/agent.db",
        "is_actionable": True,
        "dry_run": True,
        "suggest": False,
        "action": None,
        "thread_json": None,
        "thread_summary": None,
    }
    base.update(kwargs)
    return Namespace(**base)


def test_record_command_delegates_to_knowledge_record_module(monkeypatch) -> None:
    manager = load_manager_module("manager_delegate_record")
    captured: dict[str, object] = {}

    def fake_main(argv: list[str]) -> int:
        captured["argv"] = argv
        return 17

    monkeypatch.setattr(manager.record_knowledge, "main", fake_main)

    args = make_record_args()
    try:
        manager.record_knowledge_entry(args, "2026-07-07")
    except SystemExit as exc:
        assert exc.code == 17
    else:
        raise AssertionError("record_knowledge_entry should exit with delegated code")

    assert captured["argv"] == [
        "--type",
        "adr",
        "--title",
        "知识记录标题",
        "--content",
        "这是用于验证委托链路的中文内容。",
        "--date",
        "2026-07-07",
        "--background",
        "这是这次记录的背景信息。",
        "--tags",
        "知识记录,委托测试",
        "--impact",
        "high",
        "--references",
        "docs/ref.md",
        "--project",
        "mac-bootstrap",
        "--expires-at",
        "2026-07-31",
        "--why-record",
        "需要验证 lifecycle manager 只做委托。",
        "--agent",
        "codex",
        "--session-id",
        "session-123",
        "--message-id",
        "42",
        "--project-path",
        "/tmp/project",
        "--db-path",
        "/tmp/agent.db",
        "--is-actionable",
        "--dry-run",
    ]


def test_record_suggest_delegates_to_knowledge_record_suggest(monkeypatch) -> None:
    manager = load_manager_module("manager_delegate_suggest")
    captured: dict[str, object] = {}

    def fake_main(argv: list[str]) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(manager.record_knowledge, "main", fake_main)
    args = make_record_args(
        record_type=None,
        title=None,
        content=None,
        suggest=True,
        agent="codex",
        project_path="/tmp/project",
        db_path="/tmp/agent.db",
        action=["edit tags=知识管理,记录生成", "accept"],
        thread_summary="本次会话完成了知识记录建议流程优化。",
    )

    try:
        manager.record_knowledge_entry(args, "2026-07-07")
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("record_knowledge_entry should exit with delegated code")

    assert captured["argv"] == [
        "suggest",
        "--date",
        "2026-07-07",
        "--agent",
        "codex",
        "--project-path",
        "/tmp/project",
        "--db-path",
        "/tmp/agent.db",
        "--thread-summary",
        "本次会话完成了知识记录建议流程优化。",
        "--action",
        "edit tags=知识管理,记录生成",
        "--action",
        "accept",
    ]


def test_record_suggest_parser_does_not_require_direct_record_fields(monkeypatch) -> None:
    manager = load_manager_module("manager_delegate_suggest_parser")
    captured: dict[str, object] = {}

    def fake_entry(args, target_date: str) -> None:
        captured["args"] = args
        captured["target_date"] = target_date

    monkeypatch.setattr(manager, "record_knowledge_entry", fake_entry)

    manager.main(
        [
            "record",
            "--suggest",
            "--agent",
            "codex",
            "--date",
            "2026-07-07",
            "--thread-summary",
            "本次会话完成了记录建议流程。",
            "--action",
            "accept",
        ]
    )

    assert captured["target_date"] == "2026-07-07"
    assert captured["args"].suggest is True
    assert captured["args"].thread_summary == "本次会话完成了记录建议流程。"
    assert captured["args"].action == ["accept"]


def test_compat_record_script_main_delegates_to_canonical_owner() -> None:
    manager = load_manager_module("manager_delegate_compat")
    compat_path = Path(manager.__file__).with_name("record_knowledge.py")

    namespace: dict[str, object] = {
        "__file__": str(compat_path),
        "__name__": "compat_record_knowledge_under_test",
    }
    exec(compat_path.read_text(), namespace)

    class StubCanonical:
        def __init__(self) -> None:
            self.seen_argv: list[str] | None = None

        def main(self, argv: list[str] | None = None) -> int:
            self.seen_argv = argv
            return 23

    stub = StubCanonical()
    namespace["_CANONICAL"] = stub

    assert namespace["main"](["--dry-run"]) == 23
    assert stub.seen_argv == ["--dry-run"]
