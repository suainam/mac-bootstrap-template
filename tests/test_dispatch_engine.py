import importlib.util
from pathlib import Path
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


def test_lint_task_contract_valid(tmp_path: Path):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(
        """# 目标 (Outcome)
实现功能
# 验证 (Verification)
pytest tests/
# 约束 (Constraints)
无凭证
# 边界 (Boundaries)
仅本目录
# 迭代策略 (Iteration Policy)
小步迭代
# 完成条件 (Stop when)
测试通过
# 暂停条件 (Pause if)
遇到阻断
""",
        encoding="utf-8",
    )
    # Should not raise
    lint_task_contract(task_file, delegation_level="OUTCOME_ONLY")


def test_lint_task_contract_missing_section(tmp_path: Path):
    task_file = tmp_path / "TASK.md"
    task_file.write_text("# 目标\n测试", encoding="utf-8")
    with pytest.raises(TaskContractError, match="Missing mandatory sections"):
        lint_task_contract(task_file)


def test_lint_task_contract_rejects_pseudo_delegation_diff(tmp_path: Path):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(
        """# 目标
实现功能
# 验证
pytest
# 约束
无
# 边界
src/
# 迭代策略
一步
# 完成条件
通过
# 暂停条件
阻断

diff --git a/foo.py b/foo.py
@@ -1,3 +1,3 @@
-old
+new
""",
        encoding="utf-8",
    )
    with pytest.raises(TaskContractError, match="Pseudo-Delegation detected"):
        lint_task_contract(task_file, delegation_level="OUTCOME_ONLY")


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
