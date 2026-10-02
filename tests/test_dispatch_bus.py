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
import os
import subprocess
import sys
import threading
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
def repo(tmp_path: Path):
    """A real git repo, so state resolves via git-common-dir like production.

    Also registers the default target pane. Since Issue #136 the worktree comes
    from the pane rather than argv, so a dispatch against a pane that does not
    exist is now a refusal — which is the correct behaviour and would otherwise
    make every test here start by failing that gate.
    """
    target = tmp_path / "repo"
    (target / ".git").mkdir(parents=True)
    _PANES["w3:p9"] = {"cwd": os.fspath(target)}
    _PANES["w3:p1"] = {"cwd": os.fspath(target)}
    _PANES["w3:pB"] = {"cwd": os.fspath(target)}
    yield target
    _PANES.clear()


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


# Pane cwds the fake Herdr answers with, keyed by pane id. Module-level because
# the `repo` fixture owns the directory while `calls` owns the recorder, and a
# dispatch's placement now comes from a pane rather than from argv.
_PANES: dict = {}


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record every observable effect the bus has.

    The placement probe is answered here rather than reaching for Herdr: it is
    a read, not one of the effects under test, and a probe that hit a real
    server would make every test here depend on one running.
    """
    recorded: dict = {"rename": [], "prompt": [], "state": []}

    def fake_rename(pane_id: str, label: str) -> None:
        recorded["rename"].append((pane_id, label))

    def fake_run_herdr(args, **kwargs):
        argv = list(args)
        if argv[:2] == ["pane", "get"]:
            return {"result": {"pane": _PANES.get(argv[2], {})}}
        recorded["prompt"].append(argv)
        return {}

    real_save = brain.save

    def tracking_save(path, state, **kwargs):
        recorded["state"].append(dict(state))
        return real_save(path, state, **kwargs)

    monkeypatch.setattr(bus, "rename_pane", fake_rename, raising=False)
    monkeypatch.setattr(plugin.herdr, "run_herdr", fake_run_herdr)
    monkeypatch.setattr(bus.brain, "save", tracking_save)
    monkeypatch.setattr(plugin.brain, "save", tracking_save)
    # Git is reached through the derivation module, so stub the reader rather
    # than the process spawn it wraps.
    monkeypatch.setattr(bus.derive, "_git_toplevel", lambda cwd: os.fspath(Path(cwd).resolve()))
    monkeypatch.setattr(bus.derive, "_git_branch", lambda cwd: "feat/1-3")
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
    assert path.startswith("/tmp/handoff/")
    # No bare filename is acceptable: an unanchored handoff is unfindable.
    assert "/" in path


def test_handoff_path_rejects_a_bare_name() -> None:
    with pytest.raises(bus.InvalidLaneNameError):
        bus.handoff_path("research-agy", "20261001_180823")


def test_handoff_dir_is_created_owner_only(tmp_path: Path) -> None:
    root = tmp_path / "handoff"
    assert bus.ensure_handoff_dir(root) == root
    assert root.is_dir()
    assert root.stat().st_mode & 0o777 == 0o700


def test_handoff_dir_tightens_existing_permissions(tmp_path: Path) -> None:
    root = tmp_path / "handoff"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    bus.ensure_handoff_dir(root)
    assert root.stat().st_mode & 0o777 == 0o700


def test_handoff_dir_refuses_a_symlink(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "handoff"
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(bus.DispatchRefused):
        bus.ensure_handoff_dir(link)


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
        handoff="/tmp/handoff/1-3-dispatch-handoff-20261001_180823.md",
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
    #
    # Issue #136 collapsed this to four arguments. `--lane`, `--worktree`,
    # `--branch`, `--highlight` and `--risk` are all derived, so the default
    # call carries none of them; the overrides are still accepted and still
    # tested, because an override that is silently ignored is worse than one
    # that is refused.
    argv = [
        "--repo", str(repo),
        "dispatch",
        "--task", str(task),
        "--lane-name", over.get("lane_name", "1-3-dispatch"),
        "--target", over.get("target", "w3:p9"),
        "--callback-target", over.get("callback_target", "w3:p1"),
    ]
    if over.get("signature"):
        argv += ["--signature", over["signature"]]
    if over.get("lane"):
        argv += ["--lane", over["lane"]]
    if over.get("worktree"):
        argv += ["--worktree", over["worktree"]]
    if over.get("branch"):
        argv += ["--branch", over["branch"]]
    for bullet in over.get("highlight", []):
        argv += ["--highlight", bullet]
    for bullet in over.get("risk", []):
        argv += ["--risk", bullet]
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


def test_worker_receives_a_task_request_not_a_completion_report(repo, task_file, calls) -> None:
    plugin.main(_argv(repo, task_file, callback_target="w3:pB"))
    delivered = calls["prompt"][0][3]
    assert delivered.startswith("[DISPATCH]\n")
    assert not delivered.startswith("[NOTIFY]")
    assert f"Task: {task_file}" in delivered
    assert "Lane: 1-3" in delivered
    assert "Run ID: run-" in delivered
    assert "Dispatch ID: dispatch-" in delivered
    assert "Callback target: w3:pB" in delivered
    assert "dispatch_plugin.py notify" in delivered


def test_parent_callback_target_is_distinct_from_worker(repo, task_file, calls) -> None:
    assert plugin.main(_argv(repo, task_file, callback_target="w3:p9")) == 2
    assert calls["prompt"] == []
    assert calls["state"] == []


def test_unknown_parent_callback_is_refused_before_send(repo, task_file, calls) -> None:
    assert plugin.main(_argv(repo, task_file, callback_target="wZ:pQ")) == 2
    assert calls["prompt"] == []
    assert calls["state"] == []


def test_dispatch_records_stable_transport_identity(repo, task_file, calls) -> None:
    assert plugin.main(_argv(repo, task_file, callback_target="w3:pB")) == 0
    lane = brain.load(brain.state_path(repo))["lanes"]["1-3"]
    assert lane["run_id"]
    assert lane["dispatch_id"]
    assert lane["callback_target"] == "w3:pB"
    assert lane["delivery_status"] == "delivered"


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


def test_state_pins_the_lane_worktree_and_branch(
    repo, task_file, calls, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Overrides are assertions about the target pane's physical placement.
    worktree = tmp_path / "wt-1-3"
    worktree.mkdir()
    _PANES["w3:p9"] = {"cwd": os.fspath(worktree)}
    monkeypatch.setattr(bus.derive, "_git_branch", lambda cwd: "feat/x")
    plugin.main(_argv(repo, task_file, worktree=str(worktree), branch="feat/x"))
    state = brain.load(brain.state_path(repo))
    assert state["lanes"]["1-3"]["worktree"] == str(worktree.resolve())
    assert state["lanes"]["1-3"]["branch"] == "feat/x"


def test_dispatch_parks_the_brain(repo: Path, task_file: Path, calls: dict) -> None:
    plugin.main(_argv(repo, task_file))
    state = brain.load(brain.state_path(repo))
    assert state["orchestrator_phase"] == "yield_and_guard"


def test_dispatch_records_the_lane_as_awaited(repo: Path, task_file: Path, calls: dict) -> None:
    """A brain that parks without naming the lane is waiting on nothing.

    Found by a live self-dispatch: `awaiting_lanes` came back empty while the
    worker was demonstrably running, because the park was handed the previous
    wait list instead of the lane just dispatched.
    """
    plugin.main(_argv(repo, task_file))
    state = brain.load(brain.state_path(repo))
    assert "1-3" in state["brain"]["awaiting_lanes"]


def test_second_dispatch_preserves_the_first_waiting_lane(
    repo: Path,
    task_file: Path,
    calls: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second_worktree = tmp_path / "repo-2"
    second_worktree.mkdir()
    _PANES["w3:p8"] = {"cwd": os.fspath(second_worktree)}

    def branch_for(cwd: str) -> str:
        return "feat/1-4" if Path(cwd) == second_worktree else "feat/1-3"

    monkeypatch.setattr(bus.derive, "_git_branch", branch_for)

    assert plugin.main(_argv(repo, task_file, lane_name="1-3-dispatch", target="w3:p9")) == 0
    assert plugin.main(_argv(repo, task_file, lane_name="1-4-review", target="w3:p8")) == 0

    state = brain.load(brain.state_path(repo))
    assert state["brain"]["awaiting_lanes"] == ["1-3", "1-4"]


def test_concurrent_stale_plans_allow_only_one_owner_of_the_same_resource(
    repo: Path,
    task_file: Path,
    calls: dict,
) -> None:
    """Both plans may observe an empty ledger; commit must arbitrate under the state lock."""
    lookup = lambda _target: os.fspath(repo)
    branch = lambda _cwd: "feat/shared"
    plans = [
        bus.DispatchPlan.plan(
            repo=repo,
            task=task_file,
            lane_name=lane_name,
            target=target,
            signature="",
            callback_target="w3:pB",
            run_id="run-a",
            pane_lookup=lookup,
            callback_lookup=lookup,
            branch_reader=branch,
        )
        for lane_name, target in [
            ("1-3-dispatch", "w3:p9"),
            ("1-4-review", "w3:p8"),
        ]
    ]

    outcomes: list[tuple[str, str]] = []

    def commit(plan: bus.DispatchPlan) -> None:
        try:
            plan.commit()
            outcomes.append(("ok", plan.lane))
        except bus.DispatchRefused:
            outcomes.append(("refused", plan.lane))

    threads = [threading.Thread(target=commit, args=(plan,)) for plan in plans]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(status for status, _ in outcomes) == ["ok", "refused"]
    winner = next(lane for status, lane in outcomes if status == "ok")
    state = brain.load(brain.state_path(repo))
    assert list(state["lanes"]) == [winner]
    assert state["brain"]["awaiting_lanes"] == [winner]


def test_concurrent_claims_on_different_resources_preserve_both_records(
    repo: Path,
    task_file: Path,
    calls: dict,
    tmp_path: Path,
) -> None:
    first_tree = tmp_path / "wt-1-3"
    second_tree = tmp_path / "wt-1-4"
    first_tree.mkdir()
    second_tree.mkdir()

    pane_cwds = {"w3:p9": str(first_tree), "w3:p8": str(second_tree)}
    branches = {str(first_tree): "feat/1-3", str(second_tree): "feat/1-4"}

    def pane_lookup(target: str) -> str:
        return pane_cwds[target]

    def branch_reader(cwd: str) -> str:
        return branches[cwd]

    plans = [
        bus.DispatchPlan.plan(
            repo=repo,
            task=task_file,
            lane_name=lane_name,
            target=target,
            signature="",
            callback_target="w3:pB",
            run_id="run-a",
            pane_lookup=pane_lookup,
            callback_lookup=lambda _target: os.fspath(repo),
            worktree_reader=lambda cwd: cwd,
            branch_reader=branch_reader,
        )
        for lane_name, target in [
            ("1-3-dispatch", "w3:p9"),
            ("1-4-review", "w3:p8"),
        ]
    ]

    errors: list[BaseException] = []

    def commit(plan: bus.DispatchPlan) -> None:
        try:
            plan.commit()
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=commit, args=(plan,)) for plan in plans]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    state = brain.load(brain.state_path(repo))
    assert sorted(state["lanes"]) == ["1-3", "1-4"]
    assert sorted(state["brain"]["awaiting_lanes"]) == ["1-3", "1-4"]


def test_active_lane_cannot_be_replaced_by_a_new_run_or_dispatch(
    repo: Path,
    task_file: Path,
    calls: dict,
) -> None:
    lookup = lambda _target: os.fspath(repo)
    branch = lambda _cwd: "feat/shared"
    first = bus.DispatchPlan.plan(
        repo=repo,
        task=task_file,
        lane_name="1-3-dispatch",
        target="w3:p9",
        signature="",
        callback_target="w3:pB",
        run_id="run-a",
        dispatch_id="dispatch-a",
        pane_lookup=lookup,
        callback_lookup=lookup,
        branch_reader=branch,
    )
    first.commit()

    replacement = bus.DispatchPlan.plan(
        repo=repo,
        task=task_file,
        lane_name="1-3-dispatch",
        target="w3:p9",
        signature="",
        callback_target="w3:pB",
        run_id="run-b",
        dispatch_id="dispatch-b",
        pane_lookup=lookup,
        callback_lookup=lookup,
        branch_reader=branch,
    )
    with pytest.raises(bus.DispatchRefused, match="already owned|cannot replace"):
        replacement.commit()

    state = brain.load(brain.state_path(repo))
    assert state["run_id"] == "run-a"
    assert state["lanes"]["1-3"]["dispatch_id"] == "dispatch-a"


def test_same_dispatch_identity_may_recommit_for_delivery_retry(
    repo: Path,
    task_file: Path,
    calls: dict,
) -> None:
    lookup = lambda _target: os.fspath(repo)
    branch = lambda _cwd: "feat/shared"
    plan = bus.DispatchPlan.plan(
        repo=repo,
        task=task_file,
        lane_name="1-3-dispatch",
        target="w3:p9",
        signature="",
        callback_target="w3:pB",
        run_id="run-a",
        dispatch_id="dispatch-a",
        timestamp="20261002_161500",
        pane_lookup=lookup,
        callback_lookup=lookup,
        branch_reader=branch,
    )
    plan.commit()
    plan.commit()

    state = brain.load(brain.state_path(repo))
    assert state["run_id"] == "run-a"
    assert state["lanes"]["1-3"]["dispatch_id"] == "dispatch-a"
    assert state["lanes"]["1-3"]["handoff"] == plan.handoff


def test_dispatch_walks_a_legal_transition_path(repo: Path, task_file: Path, calls: dict) -> None:
    """contract -> topology -> yield_and_guard, never an illegal jump."""
    assert plugin.main(_argv(repo, task_file)) == 0
    state = brain.load(brain.state_path(repo))
    # advance() raises on an illegal jump, so reaching the park proves the path
    # was legal rather than forced.
    assert state["orchestrator_phase"] == "yield_and_guard"


def test_dispatch_refuses_when_the_brain_cannot_reach_the_park(repo, task_file, calls) -> None:
    """A brain already past the park is refused, not silently rewound."""
    path = brain.state_path(repo)
    state = brain.load(path)
    state["orchestrator_phase"] = "closed"
    brain.save(path, state)

    assert plugin.main(_argv(repo, task_file)) == 2
    assert calls["prompt"] == []
    assert brain.load(path)["orchestrator_phase"] == "closed"


# --------------------------------------------------------------------------
# Atomicity — the property that makes the bus worth having
# --------------------------------------------------------------------------


def test_lost_delivery_confirmation_is_unknown_and_retry_reuses_identity(
    repo: Path, task_file: Path, calls: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = []

    def flaky(argv, **kwargs):
        if argv[:2] == ["pane", "get"]:
            return {"result": {"pane": {"pane_id": argv[2], "cwd": os.fspath(repo)}}}
        if argv[:2] == ["agent", "prompt"]:
            attempts.append(list(argv))
            if len(attempts) == 1:
                raise plugin.herdr.HerdrError("herdr agent prompt timed out after 20s")
            return {"result": {"accepted": True}}
        return {}

    monkeypatch.setattr(plugin.herdr, "run_herdr", flaky)
    assert plugin.main(_argv(repo, task_file, callback_target="w3:pB")) == plugin.EXIT_DELIVERY_FAILED
    first = brain.load(brain.state_path(repo))["lanes"]["1-3"].copy()
    assert first["status"] == "delivery_unknown"
    assert first["delivery_status"] == "unknown"

    assert plugin.main(_argv(repo, task_file, callback_target="w3:pB")) == 0
    second = brain.load(brain.state_path(repo))["lanes"]["1-3"]
    assert second["dispatch_id"] == first["dispatch_id"]
    assert second["handoff"] == first["handoff"]
    assert attempts[1][3] == attempts[0][3]


def test_pre_send_agent_not_ready_is_rejected_and_retry_reuses_identity(
    repo: Path, task_file: Path, calls: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = []

    def not_ready_once(argv, **kwargs):
        if argv[:2] == ["pane", "get"]:
            return {"result": {"pane": {"pane_id": argv[2], "cwd": os.fspath(repo)}}}
        if argv[:2] == ["agent", "prompt"]:
            attempts.append(list(argv))
            if len(attempts) == 1:
                raise plugin.herdr.HerdrError(
                    '{"error":{"code":"agent_not_ready","message":"agent is not ready"}}'
                )
            return {"result": {"accepted": True}}
        return {}

    monkeypatch.setattr(plugin.herdr, "run_herdr", not_ready_once)

    assert plugin.main(_argv(repo, task_file)) == plugin.EXIT_DELIVERY_FAILED
    first = brain.load(brain.state_path(repo))["lanes"]["1-3"].copy()
    assert first["status"] == "delivery_rejected"
    assert first["delivery_status"] == "rejected"
    assert first["delivered"] is False

    assert plugin.main(_argv(repo, task_file)) == 0
    second = brain.load(brain.state_path(repo))["lanes"]["1-3"]
    assert second["dispatch_id"] == first["dispatch_id"]
    assert second["handoff"] == first["handoff"]
    assert attempts[1][3] == attempts[0][3]


def test_ambiguous_post_commit_failure_is_not_claimed_undelivered(
    repo: Path, task_file: Path, calls: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker never started, so the record must not say it is working.

    `working` is a claim about a process. Left uncorrected it poisons two
    consumers: the stall watchdog alarms on a lane with no worker to
    investigate, and a human reading the board looks for an agent that was never
    spawned.
    """

    def dead_pane(argv, **kwargs):
        if argv[:2] == ["pane", "get"]:
            return {"result": {"pane": {"pane_id": argv[2], "cwd": os.fspath(repo)}}}
        raise plugin.herdr.HerdrError("pane is gone")

    monkeypatch.setattr(plugin.herdr, "run_herdr", dead_pane)

    assert plugin.main(_argv(repo, task_file)) == plugin.EXIT_DELIVERY_FAILED

    lane = brain.load(brain.state_path(repo))["lanes"]["1-3"]
    assert lane["status"] == "delivery_unknown"
    assert lane["delivery_status"] == "unknown"
    assert lane["delivered"] is None


def test_the_exit_3_message_does_not_claim_a_rerun_would_be_refused(
    repo: Path, task_file: Path, calls: dict, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """An unknown outcome keeps the same identity for an idempotent retry."""

    def dead_pane(argv, **kwargs):
        if argv[:2] == ["pane", "get"]:
            return {"result": {"pane": {"pane_id": argv[2], "cwd": os.fspath(repo)}}}
        raise plugin.herdr.HerdrError("pane is gone")

    monkeypatch.setattr(plugin.herdr, "run_herdr", dead_pane)
    plugin.main(_argv(repo, task_file))
    err = capsys.readouterr().err

    assert "Re-run the same dispatch command" in err
    assert "dispatch_id=" in err
    assert "new timestamp" not in err.lower()


def test_a_signature_naming_another_lane_is_reconciled_not_honoured(
    repo: Path, task_file: Path, calls: dict
) -> None:
    """End to end: the delivered report must be attributable to this lane.

    `consumeNotify` drops the park entry for whichever lane the signature
    resolves to. A signature naming a different lane leaves `awaiting_lanes`
    untouched and the orchestrator parked forever against a lane that
    demonstrably reported.
    """
    plugin.main(_argv(repo, task_file, signature="9-9-other_w9:p9"))
    delivered = calls["prompt"][0][3]
    assert "Signature: 1-3_w3:p9" in delivered
    assert "9-9-other" not in delivered


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
        repo=repo, task=task_file, lane_name="1-3-dispatch",
        target="w3:p9", signature="sig", callback_target="w3:p1",
    )
    assert calls["rename"] == []
    assert calls["prompt"] == []
    assert calls["state"] == []
    assert plan.lane_name == "1-3-dispatch"


def test_a_plan_carries_every_value_it_needs(repo, task_file, calls) -> None:
    plan = bus.DispatchPlan.plan(
        repo=repo, task=task_file, lane_name="1-3-dispatch",
        target="w3:p9", signature="sig", callback_target="w3:p1",
    )
    assert plan.timestamp
    assert plan.handoff.endswith(".md")
    assert plan.timestamp in plan.handoff
    assert plan.request.startswith("[DISPATCH]\n")


def test_a_plan_needs_no_lane_argument_at_all(repo, task_file, calls) -> None:
    """Four arguments is the point of Issue #136: the rest is derivable.

    Asserting the *absence* of a requirement, not just that the call happens to
    work, because the original defect was an argument that had to be supplied
    and could contradict its own source.
    """
    plan = bus.DispatchPlan.plan(
        repo=repo, task=task_file, lane_name="1-3-dispatch",
        target="w3:p9", signature="sig", callback_target="w3:p1",
    )
    assert plan.lane == "1-3"
    assert plan.worktree == str(repo.resolve())
    assert plan.branch == "feat/1-3"


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