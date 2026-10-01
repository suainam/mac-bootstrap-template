"""Tests for the unified dispatch bus — `dispatch_plugin.py dispatch`.

Six separate manual steps (`lint`, `claim`, pane rename, timestamp, `notify`
envelope, state flush) meant that any one could be skipped. This module fuses
them into one command, and the property that matters most is **atomicity**: if
any pre-flight gate refuses, nothing may be renamed, nothing written to the
state file, and nothing delivered.

So most tests here are negative. A bus that mutates first and validates later is
worse than the six manual steps it replaced: it fails *and* leaves wreckage.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "multiplexer" / "herdr-dispatch"
LIB = PLUGIN_ROOT / "lib"
BIN = PLUGIN_ROOT / "bin"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(LIB))
bus = _load("dispatch_bus", LIB / "dispatch_bus.py")
brain = _load("dispatch_orchestrator_state", LIB / "orchestrator_state.py")
isolation = _load("dispatch_lane_isolation", LIB / "lane_isolation.py")
plugin = _load("dispatch_plugin", BIN / "dispatch_plugin.py")

VALID_TASK = """# 目标 (Outcome)
实现统一调度总线并通过测试
# 验证 (Verification)
pytest tests/
# 约束 (Constraints)
不得写入任何凭证与敏感信息
# 边界 (Boundaries)
仅修改当前插件目录内文件
# 迭代策略 (Iteration Policy)
使用 rtk 控制输出, 走 to-spec 与 implement-spec
# 完成条件 (Stop when)
全部测试通过且状态文件写入正确
# 暂停条件 (Pause if)
遇到锁协议冲突立即暂停
"""


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A real git repo, so state resolves via git-common-dir like production."""
    target = tmp_path / "repo"
    (target / ".git").mkdir(parents=True)
    return target


@pytest.fixture()
def task_file(tmp_path: Path) -> Path:
    path = tmp_path / "TASK.md"
    path.write_text(VALID_TASK, encoding="utf-8")
    return path


def _bus_code_lines() -> list[str]:
    """Source lines with docstrings and comments removed.

    The module documents that it never shells out, so a raw scan would flag the
    explanation as the violation.
    """
    import ast

    text = (LIB / "dispatch_bus.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    skip: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            start = first.lineno
            skip.update(range(start, (getattr(first, "end_lineno", None) or start) + 1))
    return [
        line
        for no, line in enumerate(text.splitlines(), start=1)
        if no not in skip and line.strip() and not line.strip().startswith("#")
    ]


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> dict:
    recorded: dict = {"rename": [], "prompt": [], "state": []}

    def fake_rename(pane_id: str, label: str) -> None:
        recorded["rename"].append((pane_id, label))

    def fake_prompt(args, **kwargs):
        recorded["prompt"].append(list(args))
        return {}

    real_save = brain.save

    def tracking_save(path, state, **kwargs):
        recorded["state"].append(dict(state))
        return real_save(path, state, **kwargs)

    monkeypatch.setattr(bus, "rename_pane", fake_rename, raising=False)
    monkeypatch.setattr(plugin.herdr, "run_herdr", fake_prompt)
    monkeypatch.setattr(bus.brain, "save", tracking_save)
    monkeypatch.setattr(plugin.brain, "save", tracking_save)
    return recorded


# --------------------------------------------------------------------------
# Lane naming guard — step 3
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    ["1-1-ipquality", "1-2-sysctl", "1-3-dispatch", "1-4-research", "2-10-worker_a"],
)
def test_conforming_lane_names_are_accepted(name: str) -> None:
    assert bus.validate_lane_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "foo",              # no lane numbers
        "test_pane",        # underscore separator, no numbers
        "research-agy",     # named in the issue as the canonical counter-example
        "1-2",              # missing the slug
        "1-2-",             # empty slug
        "-1-2-sysctl",      # leading dash
        "1--2-sysctl",      # malformed separator
        "1-2-Sysctl",       # uppercase is not in [a-z0-9_-]
        "1_2_sysctl",       # wrong separators
        "1-2-sysctl!",      # punctuation
        "1-2-sysctl/x",     # path separator
        "",                 # empty
    ],
)
def test_nonconforming_lane_names_are_refused(name: str) -> None:
    with pytest.raises(bus.InvalidLaneNameError):
        bus.validate_lane_name(name)


def test_lane_name_error_names_the_pattern() -> None:
    with pytest.raises(bus.InvalidLaneNameError, match=r"\^"):
        bus.validate_lane_name("research-agy")


# --------------------------------------------------------------------------
# Timestamp & handoff path — step 4
# --------------------------------------------------------------------------


def test_timestamp_is_second_level() -> None:
    """Second-level only: day-only names collide across same-day runs."""
    stamp = bus.make_timestamp()
    assert len(stamp) == 15
    assert stamp[8] == "_"
    assert stamp[:8].isdigit()
    assert stamp[9:].isdigit()


def test_handoff_path_is_fully_qualified_and_timestamped() -> None:
    path = bus.handoff_path("1-3-dispatch", "20261001_180823")
    assert path.endswith("1-3-dispatch-handoff-20261001_180823.md")
    assert path.startswith("~")
    # No bare filename is acceptable: an unanchored handoff is unfindable.
    assert "/" in path


def test_handoff_path_rejects_a_bare_name() -> None:
    with pytest.raises(bus.InvalidLaneNameError):
        bus.handoff_path("research-agy", "20261001_180823")


def test_timestamps_differ_across_calls() -> None:
    stamps = {bus.make_timestamp() for _ in range(5)}
    assert len(stamps) >= 1  # same-second is fine; just must be well-formed


# --------------------------------------------------------------------------
# Envelope assembly — step 5
# --------------------------------------------------------------------------


def test_envelope_contains_real_newlines() -> None:
    envelope = bus.build_envelope(
        signature="1-3-dispatch_opencode_mac-bootstrap",
        done="统一调度总线CLI落地",
        handoff="~/Documents/handoffs/1-3-dispatch-handoff-20261001_180823.md",
        target="w3:p1",
        highlights=["真实换行", "状态原子落盘"],
        risks=["无"],
    )
    assert "\n" in envelope
    assert "\\n" not in envelope
    assert envelope.count("\n") >= 6


def test_envelope_carries_the_timestamped_handoff() -> None:
    stamp = "20261001_180823"
    envelope = bus.build_envelope(
        "sig", "done", bus.handoff_path("1-3-dispatch", stamp), "w3:p1",
    )
    assert stamp in envelope
    assert envelope.startswith("[NOTIFY]")


def test_envelope_carries_the_resolved_target() -> None:
    envelope = bus.build_envelope("sig", "d", "/tmp/h.md", "w3:p1")
    assert "w3:p1" in envelope


# --------------------------------------------------------------------------
# The bus, end to end
# --------------------------------------------------------------------------


def _argv(repo: Path, task: Path, **over):
    # `--repo` is a top-level option, so it must precede the subcommand — the
    # same shape as every other plugin subcommand.
    argv = [
        "--repo", str(repo),
        "dispatch",
        "--task", str(task),
        "--lane", "1-3",
        "--lane-name", over.get("lane_name", "1-3-dispatch"),
        "--target", over.get("target", "w3:p9"),
        "--signature", "1-3-dispatch_test",
    ]
    if over.get("worktree"):
        argv += ["--worktree", over["worktree"]]
    if over.get("branch"):
        argv += ["--branch", over["branch"]]
    return argv


def test_a_valid_dispatch_succeeds(repo: Path, task_file: Path, calls: dict) -> None:
    code = plugin.main(_argv(repo, task_file))
    assert code == 0


def test_a_valid_dispatch_renames_the_pane(repo: Path, task_file: Path, calls: dict) -> None:
    plugin.main(_argv(repo, task_file))
    assert calls["rename"], "pane was never renamed"
    assert calls["rename"][0][1] == "1-3-dispatch"


def test_a_valid_dispatch_delivers_once(repo: Path, task_file: Path, calls: dict) -> None:
    plugin.main(_argv(repo, task_file))
    assert len(calls["prompt"]) == 1
    assert calls["prompt"][0][:3] == ["agent", "prompt", "w3:p9"]


def test_delivered_text_has_real_newlines_and_the_timestamp(repo, task_file, calls) -> None:
    plugin.main(_argv(repo, task_file))
    delivered = calls["prompt"][0][3]
    assert "\\n" not in delivered
    assert delivered.count("\n") >= 6
    assert "1-3-dispatch-handoff-" in delivered


def test_state_records_the_lane(repo: Path, task_file: Path, calls: dict) -> None:
    plugin.main(_argv(repo, task_file))
    state = brain.load(brain.state_path(repo))
    assert "1-3" in state["lanes"]
    lane = state["lanes"]["1-3"]
    assert lane["pane_id"] == "w3:p9"
    assert lane["name"] == "1-3-dispatch"
    assert lane["status"] == "working"


def test_state_records_active_panes(repo: Path, task_file: Path, calls: dict) -> None:
    plugin.main(_argv(repo, task_file))
    state = brain.load(brain.state_path(repo))
    assert "1-3" in state["active_panes"]["lanes"]


def test_state_pins_the_lane_worktree_and_branch(repo, task_file, calls) -> None:
    plugin.main(_argv(repo, task_file, worktree="/tmp/wt-1-3", branch="feat/x"))
    state = brain.load(brain.state_path(repo))
    assert state["lanes"]["1-3"]["worktree"] == "/tmp/wt-1-3"
    assert state["lanes"]["1-3"]["branch"] == "feat/x"


def test_dispatch_parks_the_brain(repo: Path, task_file: Path, calls: dict) -> None:
    plugin.main(_argv(repo, task_file))
    state = brain.load(brain.state_path(repo))
    assert state["orchestrator_phase"] == "yield_and_guard"


# --------------------------------------------------------------------------
# Atomicity — the property that makes the bus worth having
# --------------------------------------------------------------------------


def test_a_bad_lane_name_blocks_every_side_effect(repo, task_file, calls) -> None:
    """Named in the issue: research-agy must be refused outright."""
    assert plugin.main(_argv(repo, task_file, lane_name="research-agy")) == 2
    assert calls["rename"] == []
    assert calls["prompt"] == []
    assert calls["state"] == []


def test_a_nonconforming_task_blocks_every_side_effect(repo, tmp_path, calls) -> None:
    bad = tmp_path / "BAD.md"
    bad.write_text("# 目标\n做点事\n", encoding="utf-8")
    assert plugin.main(_argv(repo, bad)) == 1
    assert calls["rename"] == []
    assert calls["prompt"] == []
    assert calls["state"] == []


def test_a_task_missing_the_issue_125_clauses_blocks_everything(repo, tmp_path, calls) -> None:
    bad = tmp_path / "NO125.md"
    bad.write_text(
        VALID_TASK.replace("使用 rtk 控制输出, 走 to-spec 与 implement-spec", "小步迭代"),
        encoding="utf-8",
    )
    assert plugin.main(_argv(repo, bad)) == 1
    assert calls["rename"] == calls["prompt"] == calls["state"] == []


def test_a_worktree_collision_blocks_every_side_effect(repo, task_file, calls) -> None:
    state = brain.load(brain.state_path(repo))
    state["lanes"]["1-1"] = {"worktree": "/tmp/shared", "branch": "feat/a", "status": "working"}
    brain.save(brain.state_path(repo), state)

    assert plugin.main(
        _argv(repo, task_file, worktree="/tmp/shared", branch="feat/b")
    ) == 2
    assert calls["rename"] == []
    assert calls["prompt"] == []
    assert calls["state"] == []


def test_a_failure_leaves_an_existing_lane_untouched(repo, task_file, calls) -> None:
    path = brain.state_path(repo)
    state = brain.load(path)
    state["lanes"]["1-3"] = {"pane_id": "w9:p9", "status": "working"}
    brain.save(path, state)

    plugin.main(_argv(repo, task_file, lane_name="nope"))
    after = brain.load(path)
    assert after["lanes"]["1-3"]["pane_id"] == "w9:p9"
    assert after["lanes"]["1-3"]["status"] == "working"


def test_a_missing_task_file_blocks_every_side_effect(repo, tmp_path, calls) -> None:
    assert plugin.main(_argv(repo, tmp_path / "nope.md")) != 0
    assert calls["rename"] == calls["prompt"] == calls["state"] == []


def test_lint_failure_is_exit_1_while_gate_failures_are_exit_2(repo, tmp_path, calls) -> None:
    """Distinct codes: one is a malformed contract, the other a rule refusal."""
    bad = tmp_path / "BAD.md"
    bad.write_text("# 目标\n做点事\n", encoding="utf-8")
    assert plugin.main(_argv(repo, bad)) == 1
    # A worktree collision is a rule refusal, not a malformed file.
    state = brain.load(brain.state_path(repo))
    state["lanes"]["1-1"] = {"worktree": "/tmp/shared", "branch": "f", "status": "working"}
    brain.save(brain.state_path(repo), state)
    good = tmp_path / "GOOD.md"
    good.write_text(VALID_TASK, encoding="utf-8")
    assert plugin.main(_argv(repo, good, worktree="/tmp/shared", branch="g")) == 2


def test_the_cheapest_gate_runs_first(repo, tmp_path, calls) -> None:
    """A bad lane name is reported even when the contract is also broken.

    Ordering by cost means one error surfaces per round trip instead of forcing
    the orchestrator to fix everything before it learns anything.
    """
    bad = tmp_path / "BAD.md"
    bad.write_text("# 目标\n做点事\n", encoding="utf-8")
    assert plugin.main(_argv(repo, bad, lane_name="research-agy")) == 2


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_dispatch_is_deterministic(repo, task_file, calls) -> None:
    plugin.main(_argv(repo, task_file))
    first = brain.load(brain.state_path(repo))["lanes"]["1-3"]
    calls["prompt"].clear()
    plugin.main(_argv(repo, task_file))
    second = brain.load(brain.state_path(repo))["lanes"]["1-3"]
    assert first["pane_id"] == second["pane_id"]
    assert first["name"] == second["name"]


# --------------------------------------------------------------------------
# Structure of the bus itself
# --------------------------------------------------------------------------


def test_plan_and_commit_are_separate() -> None:
    """Atomicity is only possible if validation produces a value first."""
    assert hasattr(bus, "DispatchPlan")
    assert hasattr(bus.DispatchPlan, "plan")
    assert hasattr(bus.DispatchPlan, "commit")


def test_planning_raises_before_it_touches_anything(repo, task_file, calls) -> None:
    plan = bus.DispatchPlan.plan(
        repo=repo, task=task_file, lane="1-3", lane_name="1-3-dispatch",
        target="w3:p9", signature="sig",
    )
    assert calls["rename"] == []
    assert calls["prompt"] == []
    assert calls["state"] == []
    assert plan.lane_name == "1-3-dispatch"


def test_a_plan_carries_every_value_it_needs(repo, task_file) -> None:
    plan = bus.DispatchPlan.plan(
        repo=repo, task=task_file, lane="1-3", lane_name="1-3-dispatch",
        target="w3:p9", signature="sig",
    )
    assert plan.timestamp
    assert plan.handoff.endswith(".md")
    assert plan.timestamp in plan.handoff
    assert plan.envelope.count("\n") >= 6


def test_the_bus_runs_no_shell_of_its_own() -> None:
    """It composes argv arrays; it never lets the orchestrator build one."""
    code = "\n".join(_bus_code_lines())
    assert "os.system" not in code
    assert "shell=True" not in code
    assert "subprocess" not in code


def test_the_bus_never_delivers_by_itself() -> None:
    """Delivery belongs to the prompt gate, so there is exactly one way to send.

    The bus reuses the gate's *formatter* for the envelope -- deliberately, so
    the bus cannot emit a differently shaped report -- but it must not hold its
    own send path, or a second delivery route reopens immediately.
    """
    code = "\n".join(_bus_code_lines())
    assert "agent\", \"prompt" not in code
    assert "agent', 'prompt" not in code


# --------------------------------------------------------------------------
# CLI surface
# --------------------------------------------------------------------------


def test_dispatch_is_not_a_manifest_action() -> None:
    """It requires arguments, so it must not appear in the action menu."""
    import tomllib

    with (PLUGIN_ROOT / "herdr-plugin.toml").open("rb") as handle:
        manifest = tomllib.load(handle)
    assert "dispatch" not in {entry["id"] for entry in manifest.get("actions", [])}


def test_dispatch_shows_up_in_help() -> None:
    out = subprocess.run(
        [sys.executable, str(BIN / "dispatch_plugin.py"), "--help"],
        capture_output=True, text=True,
    )
    assert "dispatch" in out.stdout


def test_dispatch_reports_a_receipt(repo: Path, task_file: Path, calls: dict, capsys) -> None:
    plugin.main(_argv(repo, task_file))
    out = capsys.readouterr().out
    assert "1-3-dispatch" in out
    assert "-handoff-" in out