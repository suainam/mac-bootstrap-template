import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import pytest

_script_path = (
    Path(__file__).resolve().parent.parent
    / "agent-skills"
    / "local"
    / "global"
    / "dispatch"
    / "scripts"
    / "dispatch.py"
)
_spec = importlib.util.spec_from_file_location("dispatch_engine", _script_path)
assert _spec and _spec.loader
dispatch = importlib.util.module_from_spec(_spec)
sys.modules["dispatch_engine"] = dispatch
_spec.loader.exec_module(dispatch)

Phase = dispatch.Phase
OrchestratorState = dispatch.OrchestratorState
StateTransitionError = dispatch.StateTransitionError
TaskContractError = dispatch.TaskContractError
lint_task_contract = dispatch.lint_task_contract
resolve_state_file = dispatch.resolve_state_file
check_toolchain_contract = dispatch.check_toolchain_contract

# A structurally valid contract carrying *both* Issue #125 clauses. Each clause
# is a separate substring so a test can strip one without emptying the section --
# otherwise the structural check fires first and the toolchain check under test
# never runs.
_EFFICIENCY_CLAUSE = "并用 rtk 控制 token 开销"
_SKILL_CLAUSE = "使用 to-spec 与 to-tickets 执行, "
_BASE_BODY = """# 目标 (Outcome)
实现功能模块与接口测试
# 验证 (Verification)
pytest tests/
# 约束 (Constraints)
无凭证与敏感信息
# 边界 (Boundaries)
仅本工作区目录
# 迭代策略 (Iteration Policy)
小步迭代重跑检查
# 完成条件 (Stop when)
所有测试验证全部通过
# 暂停条件 (Pause if)
遇到阻断或外部依赖
"""

_CONTRACT_BODY = _BASE_BODY.replace(
    "小步迭代重跑检查", f"小步迭代重跑检查; {_SKILL_CLAUSE}{_EFFICIENCY_CLAUSE}"
)


def test_bash_wrapper_uses_the_unified_bus_for_formal_delivery():
    sh = _script_path.parent / "herdr-dispatch.sh"
    content = sh.read_text(encoding="utf-8")
    assert "herdr agent prompt" not in content
    assert 'dispatch_plugin.py"' in content
    assert '--callback-target "${HERDR_PANE_ID}"' in content
    assert '--lane-name "${NAME}"' in content


def test_bash_wrapper_rechecks_readiness_and_maps_codex_permissions():
    sh = _script_path.parent / "herdr-dispatch.sh"
    content = sh.read_text(encoding="utf-8")
    assert "START_RC=0" in content
    assert "Agent start is waiting on a trust modal" in content
    assert "READY=false" in content
    assert 'if [[ "${READY}" != "true" ]]' in content
    assert "--approve-for-me" in content
    assert "--dangerously-bypass-approvals-and-sandbox" in content
    assert "Documents/handoffs" not in content


def test_bash_wrapper_resolves_engine():
    """Anti-regression: herdr-dispatch.sh must point to real dispatch.py."""
    sh = _script_path.parent / "herdr-dispatch.sh"
    content = sh.read_text(encoding="utf-8")
    m = re.search(r'ENGINE_PY="\$\{SCRIPT_DIR\}/([^"]+)"', content)
    assert m, "ENGINE_PY not defined in bash wrapper"
    target_file = _script_path.parent / m.group(1)
    assert target_file.is_file(), f"Engine target file does not exist: {target_file}"


def test_resolve_state_file_anchors_to_common_dir(tmp_path: Path):
    """B2 & N-03: State file must be anchored to git-common-dir across worktrees."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "runner@example.com"], check=True)
    (repo / "init.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "init.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)

    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(wt), "-b", "feature"], check=True)

    main_state_file = resolve_state_file(str(repo))
    wt_state_file = resolve_state_file(str(wt))

    assert main_state_file == wt_state_file, "State file must be identical across main repo and worktrees"
    assert main_state_file.name == "ORCHESTRATOR_STATE.json"
    assert main_state_file.parent.name == "dispatch"
    assert main_state_file.parent.parent.name == ".git"


def test_lint_task_contract_valid(tmp_path: Path):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(
        """# 目标 (Outcome)
实现功能模块与接口测试
# 验证 (Verification)
pytest tests/
# 约束 (Constraints)
无凭证与敏感信息
# 边界 (Boundaries)
仅本工作区目录
# 迭代策略 (Iteration Policy)
小步迭代重跑检查; 使用 rtk 与 codebase-memory-mcp 控制开销, 执行流走 to-spec
# 完成条件 (Stop when)
所有测试验证全部通过
# 暂停条件 (Pause if)
遇到阻断或外部依赖
""",
        encoding="utf-8",
    )
    # Should not raise
    lint_task_contract(task_file)


def _contract_without(*clauses: str) -> str:
    """``_CONTRACT_BODY`` with the named clauses stripped.

    Asserts each removal actually happened. ``str.replace`` returns the input
    unchanged when the needle is absent, which silently turns a test that
    should be exercising a *missing* clause into one that exercises a present
    one -- a vacuous pass that looks green.
    """
    body = _CONTRACT_BODY
    for clause in clauses:
        assert clause in body, f"fixture no longer contains {clause!r}"
        body = body.replace(clause, "")
    return body


def test_lint_task_contract_requires_efficiency_clause(tmp_path: Path):
    """Issue #125: a contract must say how the work is done efficiently."""
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_contract_without(_EFFICIENCY_CLAUSE), encoding="utf-8")
    with pytest.raises(TaskContractError, match="效能准则"):
        lint_task_contract(task_file)


def test_lint_task_contract_requires_skill_toolchain(tmp_path: Path):
    """Issue #125: a contract must name the standard skill pipeline."""
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_contract_without(_SKILL_CLAUSE), encoding="utf-8")
    with pytest.raises(TaskContractError, match="标准 Skill 执行流"):
        lint_task_contract(task_file)


def test_a_contract_with_neither_clause_is_refused(tmp_path: Path):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(
        _contract_without(_EFFICIENCY_CLAUSE, _SKILL_CLAUSE), encoding="utf-8"
    )
    with pytest.raises(TaskContractError, match="toolchain contract"):
        lint_task_contract(task_file)


@pytest.mark.parametrize(
    "efficiency",
    ["rtk", "caveman ultra", "codebase-memory-mcp"],
)
def test_any_efficiency_clause_satisfies_the_efficiency_check(tmp_path: Path, efficiency: str):
    """Alternatives, not all-of: naming any one is enough for its own clause."""
    task_file = tmp_path / "TASK.md"
    body = _contract_without(_EFFICIENCY_CLAUSE).replace(
        "小步迭代重跑检查", f"小步迭代重跑检查, 采用 {efficiency} 方案"
    )
    assert efficiency in body
    task_file.write_text(body, encoding="utf-8")
    lint_task_contract(task_file)


@pytest.mark.parametrize(
    "skill", ["to-spec", "to-tickets", "implement-spec"]
)
def test_any_skill_clause_satisfies_the_skill_check(tmp_path: Path, skill: str):
    task_file = tmp_path / "TASK.md"
    body = _contract_without(_SKILL_CLAUSE).replace(
        "小步迭代重跑检查", f"小步迭代重跑检查, 执行流 {skill}"
    )
    assert skill in body
    task_file.write_text(body, encoding="utf-8")
    lint_task_contract(task_file)


def test_toolchain_check_is_case_insensitive(tmp_path: Path):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(
        _CONTRACT_BODY.replace("to-spec", "TO-SPEC").replace("rtk", "RTK"),
        encoding="utf-8",
    )
    lint_task_contract(task_file)


def test_allow_legacy_grandfathers_but_warns(tmp_path: Path, capsys):
    """The migration path must be loud — a skipped check must never look passed."""
    task_file = tmp_path / "TASK.md"
    task_file.write_text(
        _contract_without(_EFFICIENCY_CLAUSE, _SKILL_CLAUSE), encoding="utf-8"
    )
    lint_task_contract(task_file, allow_legacy=True)
    err = capsys.readouterr().err
    assert "allow-legacy" in err
    assert "125" in err


def test_allow_legacy_does_not_warn_on_a_compliant_contract(tmp_path: Path, capsys):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(_CONTRACT_BODY, encoding="utf-8")
    lint_task_contract(task_file, allow_legacy=True)
    assert capsys.readouterr().err == ""


def test_structural_failure_is_reported_before_the_toolchain(tmp_path: Path):
    """A file missing a whole section should hear that first."""
    task_file = tmp_path / "TASK.md"
    task_file.write_text("# 目标\n做点事\n", encoding="utf-8")
    with pytest.raises(TaskContractError, match="Missing or empty mandatory sections"):
        lint_task_contract(task_file)


def test_lint_task_contract_empty_headings(tmp_path: Path):
    """F-12: Empty headings must be rejected by density check."""
    task_file = tmp_path / "TASK.md"
    task_file.write_text(
        """# 目标
# 验证
# 约束
# 边界
# 迭代策略
# 完成条件
# 暂停条件
""",
        encoding="utf-8",
    )
    with pytest.raises(TaskContractError, match="Missing or empty mandatory sections"):
        lint_task_contract(task_file)


def test_lint_task_contract_rejects_pseudo_delegation_diff(tmp_path: Path):
    """F-13 & B3: Diff headers must trigger pseudo-delegation rejection unconditionally."""
    task_file = tmp_path / "TASK.md"
    task_file.write_text(
        """# 目标 (Outcome)
实现功能模块与接口测试
# 验证 (Verification)
pytest tests/
# 约束 (Constraints)
无凭证与敏感信息
# 边界 (Boundaries)
仅本工作区目录
# 迭代策略 (Iteration Policy)
小步迭代重跑检查
# 完成条件 (Stop when)
所有测试验证全部通过
# 暂停条件 (Pause if)
遇到阻断或外部依赖

diff --git a/foo.py b/foo.py
@@ -1 +1,2 @@
-old
+new
""",
        encoding="utf-8",
    )
    with pytest.raises(TaskContractError, match="Pseudo-Delegation detected"):
        lint_task_contract(task_file)


def test_state_machine_schema_compatibility_and_recovery(tmp_path: Path):
    """N-02 & N-06 & S1: Schema compatibility, null handling, and corrupted file tolerance."""
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"

    # Corrupted JSON should fall back gracefully
    state_file.write_text("{ truncated json", encoding="utf-8")
    recovered = OrchestratorState.load(state_file)
    assert recovered.phase == Phase.INIT

    # Null values in integer fields should not crash with TypeError (S1)
    state_file.write_text('{"phase":"init","review_round":null,"schema":null}', encoding="utf-8")
    null_tolerant = OrchestratorState.load(state_file)
    assert null_tolerant.review_round == 0
    assert null_tolerant.schema == 2

    # Doc schema compatibility & preserving extra keys
    state_file.write_text(
        """{
  "task_id": "compat-test",
  "phase": "writer_implementation",
  "active_panes": {"writer": "w1:p1"},
  "discovered_facts": {"pr": 120},
  "worktrees": {"writer": "/path/to/wt"},
  "completed_milestones": ["m1"]
}""",
        encoding="utf-8",
    )
    doc_compat = OrchestratorState.load(state_file)
    assert doc_compat.task_id == "compat-test"
    assert doc_compat.phase == Phase.WRITER_IMPLEMENTATION
    assert doc_compat.known_facts == {"pr": 120}
    assert doc_compat.lanes == {"writer": "w1:p1"}
    assert doc_compat.extra_data["worktrees"] == {"writer": "/path/to/wt"}
    assert doc_compat.extra_data["completed_milestones"] == ["m1"]

    # Verify saving preserves extra_data back to root
    doc_compat.save(state_file)
    reloaded = OrchestratorState.load(state_file)
    assert reloaded.extra_data["worktrees"] == {"writer": "/path/to/wt"}


def test_state_machine_transitions(tmp_path: Path):
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = OrchestratorState.load(state_file)
    assert state.phase == Phase.INIT

    # Init -> Writer
    state.advance(Phase.WRITER_IMPLEMENTATION)
    assert state.phase == Phase.WRITER_IMPLEMENTATION

    # Writer -> Skeptic (round 1)
    state.advance(Phase.SKEPTIC_REVIEW)
    assert state.phase == Phase.SKEPTIC_REVIEW
    assert state.review_round == 1

    # Skeptic -> Writer (re-work)
    state.advance(Phase.WRITER_IMPLEMENTATION)
    assert state.phase == Phase.WRITER_IMPLEMENTATION

    # Writer -> Skeptic (round 2)
    state.advance(Phase.SKEPTIC_REVIEW)
    assert state.review_round == 2

    # Skeptic -> Writer (re-work)
    state.advance(Phase.WRITER_IMPLEMENTATION)

    # Writer -> Skeptic (round 3 SHOULD BE BLOCKED BY CEILING)
    with pytest.raises(StateTransitionError, match="Review Convergence Ceiling reached"):
        state.advance(Phase.SKEPTIC_REVIEW)

    # Must transition to Human Gate
    state.advance(Phase.AWAITING_HUMAN_GATE)
    assert state.phase == Phase.AWAITING_HUMAN_GATE
    assert state.awaiting_human_gate is True

    # Human Gate -> Closed
    state.advance(Phase.CLOSED)
    assert state.phase == Phase.CLOSED
