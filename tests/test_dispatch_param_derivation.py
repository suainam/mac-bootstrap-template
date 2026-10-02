"""Tests for dispatch parameter derivation — Issue #136.

The bus used to demand six arguments that were already implied by other
arguments. That is not a convenience problem: ``--lane`` and ``--lane-name``
could disagree, a pasted ``--worktree`` could be stale by the time it was
audited, and ``--highlight`` was a second copy of a fact the task contract
already stated.

So the property worth testing is not "the derivation produces the right value".
It is: **a derivation that cannot complete is a refusal, never an empty value.**
Every field here feeds a gate, and a gate fed `""` is a gate that did not run.
That is the route by which two interactive agents end up sharing one worktree.
"""

from __future__ import annotations

import importlib.util
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
derive = _load("dispatch_derive", LIB / "dispatch_derive.py")
bus = _load("dispatch_bus", LIB / "dispatch_bus.py")
brain = _load("dispatch_orchestrator_state", LIB / "orchestrator_state.py")
plugin = _load("dispatch_plugin", BIN / "dispatch_plugin.py")


CONTRACT = """# 目标 (Outcome)
实施总线参数精简并通过全量测试。

# 验证 (Verification)
pytest tests/

# 约束 (Constraints)
不得写入任何凭证。

# 边界 (Boundaries)
仅修改插件目录。

# 迭代策略 (Iteration Policy)
使用 rtk 控制输出, 走 to-spec 与 implement-spec

# 完成条件 (Stop when)
全部测试通过。

# 暂停条件 (Pause if)
遇到跨平台路径歧义立即暂停。
"""


@pytest.fixture()
def task_file(tmp_path: Path) -> Path:
    path = tmp_path / "TASK.md"
    path.write_text(CONTRACT, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# 1. Lane coordinates from the lane name
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("1-1-ipquality", "1-1"),
        ("1-2-sysctl", "1-2"),
        ("1-3-dispatch", "1-3"),
        ("2-10-worker_a", "2-10"),
    ],
)
def test_lane_coordinates_are_the_name_prefix(name: str, expected: str) -> None:
    assert derive.lane_from_name(name) == expected


@pytest.mark.parametrize("name", ["research-agy", "foo", "", "1-3"])
def test_a_name_without_coordinates_refuses_rather_than_guessing(name: str) -> None:
    """Never return a plausible-looking coordinate for a name that lacks one.

    The caller validates the pattern first, so these are pattern regressions —
    but a wrong lane id keys the state document under the wrong lane, which is
    worse than a refusal that names the cause.
    """
    with pytest.raises(derive.DerivationRefused):
        derive.lane_from_name(name)


# --------------------------------------------------------------------------
# 2. Report sections parsed from the task contract
# --------------------------------------------------------------------------


def test_a_dedicated_highlights_section_wins() -> None:
    text = CONTRACT + "\n## 核心成果与证据\n- 总线参数精简落地\n- 全量测试绿灯\n"
    highlights, _ = derive.report_items_from_task(Path_text(text))
    assert highlights == ["总线参数精简落地", "全量测试绿灯"]


def test_a_dedicated_risk_section_wins() -> None:
    text = CONTRACT + "\n## 风险与遗留\n- 推导失败必须 exit 2\n"
    _, risks = derive.report_items_from_task(Path_text(text))
    assert risks == ["推导失败必须 exit 2"]


def test_an_english_heading_is_recognised() -> None:
    text = CONTRACT + "\n## Highlights\n- derived placement\n"
    highlights, _ = derive.report_items_from_task(Path_text(text))
    assert highlights == ["derived placement"]


def test_a_heading_suffix_is_ignored_when_matching() -> None:
    """`## 风险与遗留 (Risks)` must still resolve to the risk section."""
    text = CONTRACT + "\n## 风险与遗留 (Risks)\n- detached HEAD refuses\n"
    _, risks = derive.report_items_from_task(Path_text(text))
    assert risks == ["detached HEAD refuses"]


def test_the_outcome_section_is_the_fallback_highlight() -> None:
    highlights, _ = derive.report_items_from_task(Path_text(CONTRACT))
    assert highlights == ["实施总线参数精简并通过全量测试。"]


def test_the_constraint_section_is_the_fallback_risk() -> None:
    _, risks = derive.report_items_from_task(Path_text(CONTRACT))
    assert risks == ["不得写入任何凭证。"]


def test_no_section_at_all_yields_no_items_rather_than_an_invented_one() -> None:
    """An empty list renders as `- 无`, which is honest; a guess is not."""
    text = "# 标题\n没有任何相关段落。\n"
    assert derive.report_items_from_task(Path_text(text)) == ([], [])


def test_numbered_bullets_are_recognised() -> None:
    text = CONTRACT + "\n## 核心成果\n1. 第一项成果\n2) 第二项成果\n"
    highlights, _ = derive.report_items_from_task(Path_text(text))
    assert highlights == ["第一项成果", "第二项成果"]


def test_an_unreadable_task_refuses_rather_than_reporting_nothing(tmp_path: Path) -> None:
    with pytest.raises(derive.DerivationRefused):
        derive.report_items_from_task(tmp_path / "gone.md")


def test_a_long_pasted_log_is_clipped_to_one_line() -> None:
    """A contract is a human document; an unbounded read of one is a defect."""
    text = CONTRACT + "\n## 核心成果\n- " + ("很长的日志内容" * 200) + "\n"
    highlights, _ = derive.report_items_from_task(Path_text(text))
    assert len(highlights) == 1
    assert len(highlights[0]) <= derive.MAX_ITEM_CHARS


def test_at_most_a_handful_of_bullets_are_reported() -> None:
    text = CONTRACT + "\n## 核心成果\n" + "".join(f"- 第{i}项\n" for i in range(30))
    highlights, _ = derive.report_items_from_task(Path_text(text))
    assert len(highlights) == derive.MAX_ITEMS


def test_a_nested_heading_stays_inside_its_own_section() -> None:
    """A flat split would drop a checklist nested under a report section."""
    text = CONTRACT + "\n## 核心成果\n- 外层成果\n### 子项\n- 内层成果\n"
    highlights, _ = derive.report_items_from_task(Path_text(text))
    assert "外层成果" in highlights


def test_a_hash_inside_a_fenced_block_is_not_a_section() -> None:
    text = CONTRACT + "\n## 核心成果\n- 真成果\n\n```bash\n# 核心成果与证据\n- 假的\n```\n"
    highlights, _ = derive.report_items_from_task(Path_text(text))
    assert highlights == ["真成果"]


def test_an_unclosed_fence_does_not_silently_empty_the_report() -> None:
    """A mistyped closing marker must not turn a stated risk into "- 无".

    Dropping the rest of the document produces a report that asserts the lane
    has nothing to say, with no refusal and no note. Putting the lines back
    costs a slightly mis-parsed section; silently losing the content costs a
    false statement delivered to the worker.
    """
    text = CONTRACT + "\n## 风险与遗留\n- 真实风险\n\n```bash\nherdr pane get\n"  # never closed
    _, risks = derive.report_items_from_task(Path_text(text))
    assert "真实风险" in risks


def test_a_mismatched_closing_marker_does_not_empty_the_report() -> None:
    text = CONTRACT + "\n## 风险与遗留\n- 真实风险\n\n```bash\necho hi\n~~~\n"
    _, risks = derive.report_items_from_task(Path_text(text))
    assert "真实风险" in risks


def test_a_derived_bullet_never_carries_a_shell_placeholder() -> None:
    """A contract is written for an orchestrator and is full of `${ORCH_PANE}`.

    Quoting one of its sentences into the worker's envelope would both be
    meaningless to the worker and trip the prompt gate — refusing the dispatch
    over prose the caller never chose to send.
    """
    text = CONTRACT.replace(
        "不得写入任何凭证。", "运行前先设置 $GATE 与 ${WORKER_PANE}。"
    )
    _, risks = derive.report_items_from_task(Path_text(text))
    assert "$GATE" not in risks[0]
    assert "${WORKER_PANE}" not in risks[0]


def test_an_angle_placeholder_in_a_derived_bullet_is_neutralised() -> None:
    text = CONTRACT.replace("不得写入任何凭证。", "按 <pane_id> 回调父面板。")
    _, risks = derive.report_items_from_task(Path_text(text))
    assert "<pane_id>" not in risks[0]


def Path_text(text: str):  # noqa: N802 - a tiny helper, not a real path
    """Adapt a string to the Path the reader wants without touching disk."""
    import tempfile

    handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return Path(handle.name)


# --------------------------------------------------------------------------
# 3. Placement derived from the target pane
# --------------------------------------------------------------------------


def test_placement_comes_from_the_pane_cwd_and_its_git_head(tmp_path: Path) -> None:
    placement = derive.derive_placement(
        "w3:p9",
        pane_lookup=lambda target: str(tmp_path),
        worktree_reader=lambda cwd: cwd,
        branch_reader=lambda cwd: "feat/1-3",
    )
    assert placement.worktree == str(tmp_path.resolve())
    assert placement.branch == "feat/1-3"


def test_a_pane_with_no_cwd_refuses(tmp_path: Path) -> None:
    """The empty-value escape hatch: this is the case that must not exist."""
    with pytest.raises(derive.DerivationRefused) as excinfo:
        derive.derive_placement(
            "w3:p9",
            pane_lookup=lambda target: "",
            worktree_reader=lambda cwd: cwd,
            branch_reader=lambda c: "b",
        )
    assert "no cwd" in str(excinfo.value)


def test_a_failing_pane_probe_refuses() -> None:
    def boom(target: str) -> str:
        raise RuntimeError("socket closed")

    with pytest.raises(derive.DerivationRefused):
        derive.derive_placement(
            "w3:p9",
            pane_lookup=boom,
            worktree_reader=lambda cwd: cwd,
            branch_reader=lambda c: "b",
        )


def test_a_missing_target_refuses() -> None:
    with pytest.raises(derive.DerivationRefused):
        derive.derive_placement(
            "",
            pane_lookup=lambda t: "/tmp",
            worktree_reader=lambda cwd: cwd,
            branch_reader=lambda c: "b",
        )


def test_a_stale_cwd_that_is_not_a_directory_refuses() -> None:
    with pytest.raises(derive.DerivationRefused) as excinfo:
        derive.derive_placement(
            "w3:p9",
            pane_lookup=lambda target: "/nonexistent/wt/1-3",
            worktree_reader=lambda cwd: cwd,
            branch_reader=lambda c: "b",
        )
    assert "not a directory" in str(excinfo.value)


def test_a_detached_head_refuses_rather_than_claiming_the_literal_head() -> None:
    """`rev-parse --abbrev-ref HEAD` answers `HEAD` when detached.

    Claiming a branch named "HEAD" would look successful and isolate nothing.
    """
    with pytest.raises(derive.DerivationRefused) as excinfo:
        derive.derive_placement(
            "w3:p9",
            pane_lookup=lambda target: "/tmp",
            worktree_reader=lambda cwd: cwd,
            branch_reader=lambda cwd: "HEAD",
        )
    assert "detached HEAD" in str(excinfo.value)


def test_an_empty_branch_refuses() -> None:
    with pytest.raises(derive.DerivationRefused):
        derive.derive_placement(
            "w3:p9",
            pane_lookup=lambda target: "/tmp",
            worktree_reader=lambda cwd: cwd,
            branch_reader=lambda cwd: "  ",
        )


def test_a_non_git_directory_refuses_rather_than_returning_empty() -> None:
    """The real probe, against a directory git does not recognise."""
    with pytest.raises(derive.DerivationRefused):
        derive.derive_placement(
            "w3:p9", pane_lookup=lambda target: "/", branch_reader=None
        )


def test_real_pane_cwd_inside_a_repo_claims_the_git_worktree_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subdir = repo / "src" / "nested"
    subdir.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "dispatch-test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Dispatch Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat/live"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-qm", "init"], check=True)

    placement = derive.derive_placement("w3:p9", pane_lookup=lambda _target: str(subdir))

    assert placement.worktree == str(repo.resolve())
    assert placement.branch == "feat/live"


def test_pane_in_an_existing_non_git_directory_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(derive.DerivationRefused, match="Git worktree"):
        derive.derive_placement("w3:p9", pane_lookup=lambda _target: str(plain))


# --------------------------------------------------------------------------
# Integration: the bus uses the derivations and refuses on failure
# --------------------------------------------------------------------------


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


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    (target / ".git").mkdir(parents=True)
    return target


def _plan(repo: Path, task: Path, **over):
    kwargs = dict(
        repo=repo,
        task=task,
        lane_name="1-3-dispatch",
        target="w3:p9",
        signature="sig",
        callback_target="w3:p1",
        pane_lookup=over.pop("pane_lookup", lambda target: str(repo)),
        callback_lookup=over.pop("callback_lookup", lambda target: str(repo)),
        worktree_reader=over.pop("worktree_reader", lambda cwd: cwd),
        branch_reader=over.pop("branch_reader", lambda cwd: "feat/1-3"),
    )
    kwargs.update(over)
    return bus.DispatchPlan.plan(**kwargs)


def test_the_lane_is_keyed_under_the_derived_coordinates(repo, task_file) -> None:
    plan = _plan(repo, task_file)
    assert plan.lane == "1-3"


def test_a_stale_lane_argument_is_reported_not_honoured(repo, task_file) -> None:
    plan = _plan(repo, task_file, lane="9-9")
    assert plan.lane == "1-3"
    assert any("9-9" in note for note in plan.notes)


def test_the_placement_is_recorded_in_the_plan(repo, task_file) -> None:
    plan = _plan(repo, task_file)
    assert plan.worktree == str(repo.resolve())
    assert plan.branch == "feat/1-3"


def test_the_report_is_filled_from_the_contract(repo, task_file) -> None:
    plan = _plan(repo, task_file)
    assert plan.highlights == ["实施总线参数精简并通过全量测试。"]
    assert plan.risks == ["不得写入任何凭证。"]


def test_explicit_bullets_override_the_contract(repo, task_file) -> None:
    plan = _plan(repo, task_file, highlights=["手工指定"], risks=["手工风险"])
    assert plan.highlights == ["手工指定"]
    assert plan.risks == ["手工风险"]


def test_a_failed_placement_derivation_refuses_before_anything_happens(repo, task_file, calls) -> None:
    with pytest.raises(bus.DispatchRefused):
        _plan(repo, task_file, pane_lookup=lambda target: "")
    assert calls["rename"] == calls["prompt"] == calls["state"] == []


def test_a_derivation_refusal_is_exit_2_not_exit_1(repo, task_file) -> None:
    """1 means 'fix your task file'; 2 means 'this lane is unsafe'. A failed
    derivation is the second kind, and reporting it as the first would send an
    orchestrator to edit a contract that is already correct."""
    with pytest.raises(bus.DispatchRefused) as excinfo:
        _plan(repo, task_file, pane_lookup=lambda target: "")
    assert excinfo.value.exit_code == 2


def test_a_half_supplied_placement_is_derived_rather_than_left_incomplete(repo, task_file) -> None:
    """(worktree, "") would reach the claim gate as a lane that claims a
    directory but no branch — the interleaved-commits failure with one leg
    removed."""
    plan = _plan(repo, task_file, worktree=str(repo))
    assert plan.worktree == str(repo.resolve())
    assert plan.branch == "feat/1-3"


def test_a_supplied_worktree_must_match_the_target_pane(repo, task_file) -> None:
    """An override is an assertion about the physical pane, not a replacement for it."""
    other = tmp_path_for(repo) / "elsewhere"
    other.mkdir()
    with pytest.raises(bus.DispatchRefused) as excinfo:
        _plan(
            repo,
            task_file,
            worktree=str(other),
            pane_lookup=lambda target: str(repo),
            branch_reader=lambda cwd: "feat/1-3",
        )
    assert "does not match" in str(excinfo.value)


def test_a_named_worktree_with_no_branch_refuses(repo, task_file) -> None:
    with pytest.raises(bus.DispatchRefused):
        _plan(repo, task_file, worktree=str(tmp_path_for(repo) / "missing"))


def test_a_supplied_branch_disagreeing_with_the_pane_is_refused(repo, task_file) -> None:
    """A declared branch cannot replace the branch physically checked out in the worker tree."""
    with pytest.raises(bus.DispatchRefused) as excinfo:
        _plan(repo, task_file, branch="feat/somewhere-else")
    assert "does not match" in str(excinfo.value)


def tmp_path_for(repo: Path) -> Path:
    """A sibling of `repo` under the same pytest tmp root."""
    return repo.parent


def test_both_halves_supplied_are_still_verified_against_the_pane(repo, task_file) -> None:
    plan = _plan(
        repo,
        task_file,
        worktree=str(repo),
        branch="feat/1-3",
        pane_lookup=lambda target: str(repo),
        branch_reader=lambda cwd: "feat/1-3",
    )
    assert (plan.worktree, plan.branch) == (str(repo.resolve()), "feat/1-3")


def test_an_explicit_detached_head_is_refused_like_a_derived_one(repo, task_file) -> None:
    """The documented remedy must not reproduce the refusal it is meant to fix.

    A pane on a detached HEAD makes the derived path refuse, and the documented
    answer is "pass the values explicitly". If the explicit path skipped
    validation, `--branch HEAD` would sail through and record a claim that
    isolates nothing.
    """
    worktree = repo.parent / "wt-detached"
    worktree.mkdir(exist_ok=True)
    with pytest.raises(bus.DispatchRefused):
        _plan(repo, task_file, worktree=str(worktree), branch="HEAD")


def test_an_explicit_worktree_that_does_not_exist_is_refused(repo, task_file) -> None:
    """A claim on a missing path isolates nothing, so the collision it was
    meant to catch goes undetected."""
    with pytest.raises(bus.DispatchRefused) as excinfo:
        _plan(repo, task_file, worktree=str(repo.parent / "typo-1-3"), branch="feat/x")
    assert "not a directory" in str(excinfo.value)


def test_an_explicit_tilde_worktree_is_expanded_before_matching_the_pane(repo, task_file) -> None:
    """Equivalent spellings of the physical pane cwd remain valid assertions."""
    home = repo.parent / "home"
    wt = home / "wt"
    wt.mkdir(parents=True)
    import os as _os

    previous = _os.environ.get("HOME")
    _os.environ["HOME"] = str(home)
    try:
        plan = _plan(
            repo,
            task_file,
            worktree="~/wt",
            branch="feat/x",
            pane_lookup=lambda target: str(wt),
            branch_reader=lambda cwd: "feat/x",
        )
    finally:
        if previous is None:
            _os.environ.pop("HOME", None)
        else:
            _os.environ["HOME"] = previous
    assert plan.worktree == str(wt.resolve())


def test_the_receipt_shows_what_was_derived(repo, task_file) -> None:
    plan = _plan(repo, task_file)
    out = bus.receipt(plan)
    assert "derived" in out
    assert "feat/1-3" in out


def test_a_derived_claim_still_collides_with_a_live_lane(repo, task_file) -> None:
    """Deriving the placement must not weaken the gate it feeds."""
    path = brain.state_path(repo)
    state = brain.load(path)
    state["lanes"]["1-1"] = {
        "worktree": str(repo.resolve()),
        "branch": "feat/1-3",
        "status": "working",
    }
    brain.save(path, state)

    with pytest.raises(bus.DispatchRefused):
        _plan(repo, task_file)


def test_a_blank_bullet_override_does_not_defeat_derivation(repo, task_file) -> None:
    """`--highlight ""` is truthy as a list element.

    Left alone it would suppress the derivation and put an empty `- ` bullet in
    the worker's report — a lane told it achieved nothing, by a flag the caller
    passed empty.
    """
    plan = _plan(repo, task_file, highlights=[""], risks=["  "])
    assert plan.highlights == ["实施总线参数精简并通过全量测试。"]
    assert plan.risks == ["不得写入任何凭证。"]


# --------------------------------------------------------------------------
# The derived signature must be attributable back to the lane
# --------------------------------------------------------------------------


def test_the_derived_signature_leads_with_the_lane_id(repo, task_file) -> None:
    """The brain parks on lane ids, so the report must name one.

    `laneFromSignature` reads the prefix of the signature to decide which lane
    woke it. A signature derived from the lane *name* would not resolve to the
    lane the brain is waiting on, and `awaiting_lanes` would never empty — the
    orchestrator would sit parked on a lane that demonstrably reported.
    """
    plan = _plan(repo, task_file, signature="")
    assert plan.signature == "1-3_w3:p9"


def test_a_signature_naming_another_lane_is_rewritten_and_reported(repo, task_file) -> None:
    """The blocker: a mismatched signature parks the brain forever.

    `consumeNotify` attributes a report by the signature's leading token and
    drops that lane's park entry. A signature naming a lane the brain is *not*
    waiting on therefore leaves `awaiting_lanes` untouched — the orchestrator
    re-nudges forever against a lane that demonstrably reported.
    """
    plan = _plan(repo, task_file, signature="9-9-other_w9:p9")
    assert plan.signature == "1-3_w3:p9"
    assert any("9-9-other" in note for note in plan.notes)


def test_a_pane_coordinate_signature_is_rewritten_too(repo, task_file) -> None:
    """`w3:p9_...` names a pane, not a lane — so it names the wrong thing here.

    This is the form the dispatch SKILL.md used to recommend. It is exactly the
    shape that deadlocks: the brain awaits `1-3`, the report resolves to `w3:p9`.
    """
    plan = _plan(repo, task_file, signature="w3:p9_opencode_mac-bootstrap")
    assert plan.signature == "1-3_w3:p9"


def test_a_signature_already_naming_the_lane_is_kept_verbatim(repo, task_file) -> None:
    """Reconciliation owns the prefix, not the whole string.

    A caller who wants a richer signature — an agent kind, a repo slug — keeps
    it, as long as the attribution prefix is right.
    """
    plan = _plan(repo, task_file, signature="1-3_opencode_mac-bootstrap")
    assert plan.signature == "1-3_opencode_mac-bootstrap"
    assert not any("rewritten" in note for note in plan.notes)


def test_an_empty_signature_is_adopted_not_rewritten(repo, task_file) -> None:
    """No caller input, so nothing to report — a note would be noise."""
    plan = _plan(repo, task_file, signature="")
    assert plan.signature == "1-3_w3:p9"
    assert not any("rewritten" in note for note in plan.notes)


@pytest.mark.parametrize(
    "signature,named",
    [
        ("1-3_opencode_repo", "1-3"),
        ("w3:p9_opencode_repo", "w3:p9"),
        ("2-10_w9:p2_codex", "2-10"),
        ("no-underscore", ""),
        # A bare lane *name* is not a signature: the lane id has to be a
        # complete leading token, or the suffix would be read as part of it.
        ("1-3-dispatch", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_the_python_signature_parser_reads_both_forms(signature, named) -> None:
    assert bus.signature_lane(signature or "") == named