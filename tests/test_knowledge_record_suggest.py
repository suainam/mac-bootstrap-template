from __future__ import annotations

import importlib.util
import sqlite3
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


TEMPLATE_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = (
    TEMPLATE_ROOT
    / "agent-skills"
    / "local"
    / "mac-bootstrap"
    / "knowledge-record"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR.resolve()))


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


thread_capture = load_module("thread_capture")
evidence_collect = load_module("evidence_collect")
suggestion_engine = load_module("suggestion_engine")
confirmation_flow = load_module("confirmation_flow")
suggest_record = load_module("suggest_record")
record_knowledge = load_module("record_knowledge")


def make_thread(text: str):
    return thread_capture.ThreadPacket(
        messages=[
            thread_capture.ThreadMessage(role="user", content="帮我沉淀这次工作"),
            thread_capture.ThreadMessage(role="assistant", content=text),
        ]
    )


def make_evidence() -> object:
    return evidence_collect.EvidencePacket(
        worktree_summary="修改了 knowledge-record 的建议流程代码。",
        test_summary="测试通过：30 passed。",
        command_summary="执行过 pytest 和 sqlite 回查命令。",
        references=[
            "template/agent-skills/local/mac-bootstrap/knowledge-record/scripts/suggest_record.py"
        ],
    )


def test_capture_current_thread_from_environment_json() -> None:
    env = {
        "KNOWLEDGE_RECORD_THREAD_JSON": (
            '[{"role":"user","content":"需求"},'
            '{"role":"assistant","content":"实现了可复用规则"}]'
        )
    }

    packet = thread_capture.capture_current_thread(env)

    assert [message.role for message in packet.messages] == ["user", "assistant"]
    assert packet.combined_text() == "user: 需求\nassistant: 实现了可复用规则"


def test_capture_current_thread_from_agent_summary_argument() -> None:
    packet = thread_capture.capture_current_thread(
        {},
        thread_summary="本次会话完成了知识记录建议流程优化。",
    )

    assert [message.role for message in packet.messages] == ["user", "assistant"]
    assert "知识记录建议流程优化" in packet.combined_text()


def test_capture_current_thread_fails_without_current_thread() -> None:
    with pytest.raises(RuntimeError, match="current agent thread"):
        thread_capture.capture_current_thread({})


def test_collect_repo_evidence_uses_env_summaries(tmp_path: Path) -> None:
    env = {
        "KNOWLEDGE_RECORD_TEST_SUMMARY": "测试通过：42 passed。",
        "KNOWLEDGE_RECORD_COMMAND_SUMMARY": "关键命令：pytest。",
    }

    packet = evidence_collect.collect_repo_evidence(tmp_path, env)

    assert "测试通过" in packet.test_summary
    assert "关键命令" in packet.command_summary
    assert packet.references == []


def test_classification_priority_prefers_card_over_adr_and_daily() -> None:
    thread = make_thread("本次确定了边界，也总结出可复用规则和方法，今天完成了实现。")

    draft = suggestion_engine.suggest_record(thread, make_evidence(), agent_type="codex")

    assert draft.record_type == "card"
    assert "可复用" in draft.suggestion_reason


def test_classification_falls_back_to_adr_before_daily() -> None:
    thread = make_thread("本次决定恢复记录技能边界，明确管理入口只负责委托，并说明取舍原因。")

    draft = suggestion_engine.suggest_record(thread, make_evidence(), agent_type="codex")

    assert draft.record_type == "adr"
    assert draft.background
    assert draft.references


def test_classification_uses_daily_for_work_summary() -> None:
    thread = make_thread("本次完成了测试、文档和命令验证，整理了会话完成事项。")

    draft = suggestion_engine.suggest_record(thread, make_evidence(), agent_type="codex")

    assert draft.record_type == "daily"
    assert "本次会话" in draft.content


def test_suggestion_preserves_readable_technical_terms_when_chinese_dominant() -> None:
    draft = suggestion_engine.suggest_record(
        make_thread("本次优化 knowledge-record 和 CLI 调用体验，保留严格校验。"),
        make_evidence(),
        agent_type="codex",
    )

    assert "knowledge-record" in draft.content
    assert "CLI" in draft.content


def test_generated_draft_passes_strict_writer_validation() -> None:
    draft = suggestion_engine.suggest_record(
        make_thread("本次沉淀了可复用规则和方法，后续可照此处理记录生成。"),
        make_evidence(),
        agent_type="codex",
    )

    args = draft.to_record_args(date="2026-07-07", project_path="/tmp/project")
    record = record_knowledge.build_record(args)

    assert record["record_type"] == draft.record_type
    assert record["agent_type"] == "codex"


def test_optional_llm_draft_overrides_template_and_still_validates() -> None:
    captured = {}

    def fake_runner(command, **kwargs):
        captured["command"] = command
        captured["prompt"] = kwargs["input"]
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"title":"知识记录建议流程升级",'
                '"content":"本次会话完成了知识记录建议流程升级，保留了严格保存闸口。",'
                '"background":"当前工作围绕记录生成、确认和保存边界展开。",'
                '"tags":"知识管理,记录生成,严格校验",'
                '"why_record":"需要沉淀这次建议生成流程，避免后续管理入口丢失信息。",'
                '"references":"template/agent-skills/local/mac-bootstrap/knowledge-record/scripts/suggestion_engine.py"}'
            ),
        )

    draft = suggestion_engine.suggest_record(
        make_thread("本次沉淀了可复用规则和方法，后续可照此处理记录生成。"),
        make_evidence(),
        agent_type="codex",
        env={"KNOWLEDGE_RECORD_LLM_CMD": "fake-llm --json"},
        runner=fake_runner,
    )

    assert captured["command"] == ["fake-llm", "--json"]
    assert "当前会话" in captured["prompt"]
    assert draft.title == "知识记录建议流程升级"
    assert "可选 LLM" in draft.suggestion_reason
    record = record_knowledge.build_record(
        draft.to_record_args(date="2026-07-07", project_path="/tmp/project")
    )
    assert record["tags"] == "知识管理,记录生成,严格校验"


def test_optional_llm_invalid_output_falls_back_to_template() -> None:
    def fake_runner(_command, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="not json")

    draft = suggestion_engine.suggest_record(
        make_thread("本次沉淀了可复用规则和方法。"),
        make_evidence(),
        agent_type="codex",
        env={"KNOWLEDGE_RECORD_LLM_CMD": "fake-llm"},
        runner=fake_runner,
    )

    assert draft.title == "沉淀本次会话的可复用知识"


def test_confirmation_accept_saves_through_writer(tmp_path: Path) -> None:
    db_path = tmp_path / "records.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((TEMPLATE_ROOT / "agent" / "data-hub" / "schema.sql").read_text())
    conn.close()
    draft = suggestion_engine.suggest_record(
        make_thread("本次沉淀了可复用规则和方法，后续可照此处理记录生成。"),
        make_evidence(),
        agent_type="codex",
    )

    result = confirmation_flow.confirm_draft(
        draft,
        actions=["accept"],
        save_callback=lambda accepted: suggest_record.save_draft(
            accepted,
            date="2026-07-07",
            db_path=str(db_path),
            project_path="/tmp/project",
        ),
    )

    assert result.status == "accepted"
    with sqlite3.connect(db_path) as check:
        count = check.execute("SELECT COUNT(*) FROM knowledge_records").fetchone()[0]
    assert count == 1


def test_confirmation_cancel_does_not_save() -> None:
    draft = suggestion_engine.suggest_record(
        make_thread("本次沉淀了可复用规则和方法。"),
        make_evidence(),
        agent_type="codex",
    )
    called = False

    def save_callback(_draft):
        nonlocal called
        called = True
        return "saved"

    result = confirmation_flow.confirm_draft(draft, actions=["cancel"], save_callback=save_callback)

    assert result.status == "canceled"
    assert called is False


def test_confirmation_edits_allowed_fields_before_save() -> None:
    draft = suggestion_engine.suggest_record(
        make_thread("本次沉淀了可复用规则和方法。"),
        make_evidence(),
        agent_type="codex",
    )
    saved = {}

    result = confirmation_flow.confirm_draft(
        draft,
        actions=[
            "edit title=更新后的中文标题",
            "edit tags=知识管理,记录生成",
            "edit why_record=需要保留这次生成规则。",
            "accept",
        ],
        save_callback=lambda accepted: saved.setdefault("draft", accepted),
    )

    assert result.status == "accepted"
    assert saved["draft"].title == "更新后的中文标题"
    assert saved["draft"].tags == "知识管理,记录生成"
    assert saved["draft"].why_record == "需要保留这次生成规则。"


def test_confirmation_regenerate_replaces_draft() -> None:
    first = suggestion_engine.suggest_record(
        make_thread("本次沉淀了可复用规则和方法。"),
        make_evidence(),
        agent_type="codex",
    )
    second = suggestion_engine.RecordDraft(
        record_type="daily",
        title="本次会话完成事项总结",
        content="本次会话完成了建议流程验证。",
        background=None,
        tags="知识管理,会话总结",
        why_record="需要保留本次会话完成事项。",
        references=None,
        agent_type="codex",
        suggestion_reason="重新生成",
        confidence=0.7,
    )
    saved = {}

    result = confirmation_flow.confirm_draft(
        first,
        actions=["regenerate", "accept"],
        regenerate_callback=lambda: second,
        save_callback=lambda accepted: saved.setdefault("draft", accepted),
    )

    assert result.status == "accepted"
    assert saved["draft"].record_type == "daily"


def test_record_knowledge_dispatches_suggest(monkeypatch) -> None:
    captured = {}

    class StubSuggest:
        def main(self, argv):
            captured["argv"] = argv
            return 9

    monkeypatch.setattr(record_knowledge, "_load_suggest_module", lambda: StubSuggest())

    assert record_knowledge.main(["suggest", "--action", "cancel"]) == 9
    assert captured["argv"] == ["--action", "cancel"]


def test_suggest_main_accepts_thread_summary_and_prints_saved_record(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "records.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((TEMPLATE_ROOT / "agent" / "data-hub" / "schema.sql").read_text())
    conn.close()

    exit_code = suggest_record.main(
        [
            "--thread-summary",
            "本次会话完成了知识记录建议流程优化，并保留严格校验。",
            "--action",
            "accept",
            "--db-path",
            str(db_path),
            "--project-path",
            "/tmp/project",
            "--date",
            "2026-07-07",
            "--agent",
            "codex",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Saved knowledge record:" in output
    assert "content:" in output
    assert "why_record:" in output
    assert "candidate_date: 2026-07-07" in output
