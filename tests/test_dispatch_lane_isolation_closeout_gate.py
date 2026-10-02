"""Tests for the 1-Lane-1-Worktree-1-Branch gate and the Closeout gate.

Both gates exist because the failure they prevent is *silent*: sharing a
worktree corrupts two lanes at once, and closing a pane before closeout
completes drops the push, the pointer update and the PR merge on the floor.
Neither symptom names its cause, so each gate is pinned here by the case that
produced the lesson.

Most tests feed the gates a *violating* input on purpose. A gate that only ever
passes is worse than no gate, because it looks like enforcement.
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
herdr = _load("dispatch_herdr_client", LIB / "herdr_client.py")
isolation = _load("dispatch_lane_isolation", LIB / "lane_isolation.py")
gate = _load("dispatch_closeout_gate", LIB / "closeout_gate.py")
brain = _load("dispatch_orchestrator_state", LIB / "orchestrator_state.py")
plugin = _load("dispatch_plugin", BIN / "dispatch_plugin.py")


# --------------------------------------------------------------------------
# Path normalisation
# --------------------------------------------------------------------------


def test_worktree_paths_are_compared_by_resolution_not_by_string() -> None:
    """Two spellings of one directory must collide.

    A relative path and its absolute form name the same inode; letting them
    through would hand the stomp protection straight back.
    """
    resolved = isolation.normalise_path("/tmp/wt-a")
    assert isolation.normalise_path("/tmp/wt-a/") == resolved
    assert isolation.normalise_path("/tmp/./wt-a") == resolved


def test_normalise_handles_empty_and_unresolvable_paths() -> None:
    assert isolation.normalise_path("") == ""
    assert isolation.normalise_path(None) == ""  # type: ignore[arg-type]


def test_user_relative_paths_expand() -> None:
    assert isolation.normalise_path("~/wt-a").startswith(str(Path.home()))


# --------------------------------------------------------------------------
# Claim projection
# --------------------------------------------------------------------------


def test_lanes_without_a_worktree_or_branch_are_not_claims() -> None:
    """A lane with no physical footprint cannot collide with anything."""
    lanes = {"1-1": {"pane_id": "w3:p2", "status": "working"}}
    assert isolation.read_claims(lanes) == []


def test_claims_read_from_worktree_or_cwd() -> None:
    """Migration tolerance: older lanes recorded cwd instead of worktree."""
    lanes = {
        "1-1": {"worktree": "/tmp/a", "branch": "feat/a"},
        "1-2": {"cwd": "/tmp/b", "branch": "feat/b"},
        "1-3": {"pane_id": "w3:p9"},
    }
    claims = {c.lane_id: c for c in isolation.read_claims(lanes)}
    assert claims["1-1"].worktree == "/tmp/a"
    assert claims["1-2"].worktree == "/tmp/b"
    assert "1-3" not in claims


def test_claims_tolerate_a_malformed_lane_entry() -> None:
    assert isolation.read_claims({"1-1": "not-a-mapping"}) == []


# --------------------------------------------------------------------------
# The anti-stomping case
# --------------------------------------------------------------------------


def test_second_lane_reusing_a_worktree_is_refused() -> None:
    """The exact lesson: 1-2 reusing 1-1's worktree must raise, not warn."""
    lanes = {"1-1": {"worktree": "/tmp/nat-hk96", "branch": "feat/1-1", "status": "working"}}
    with pytest.raises(isolation.LaneCollisionError) as excinfo:
        isolation.claim_lane(lanes, "1-2", worktree="/tmp/nat-hk96", branch="feat/1-2")

    err = excinfo.value
    assert err.lane_id == "1-2"
    assert err.holder == "1-1"
    assert err.resource == "worktree"
    assert "1 Lane = 1 Worktree = 1 Branch" in str(err)


def test_second_lane_reusing_a_branch_is_refused() -> None:
    """Distinct worktrees are not enough; a shared branch still interleaves."""
    lanes = {"1-1": {"worktree": "/tmp/a", "branch": "feat/shared", "status": "working"}}
    with pytest.raises(isolation.LaneCollisionError) as excinfo:
        isolation.claim_lane(lanes, "1-2", worktree="/tmp/b", branch="feat/shared")
    assert excinfo.value.holder == "1-1"
    assert excinfo.value.resource == "branch"


def test_collision_is_detected_through_a_different_path_spelling() -> None:
    lanes = {"1-1": {"worktree": "/tmp/nat-hk96", "branch": "feat/1-1", "status": "working"}}
    audit = isolation.audit_claim(
        lanes, "1-2", worktree="/tmp/nat-hk96/", branch="feat/1-2"
    )
    assert not audit.ok


def test_independent_lanes_both_claim_cleanly() -> None:
    """The gate must not block the legitimate parallel case."""
    lanes = {"1-1": {"worktree": "/tmp/a", "branch": "feat/a", "status": "working"}}
    audit = isolation.audit_claim(lanes, "1-2", worktree="/tmp/b", branch="feat/b")
    assert audit.ok
    assert audit.violations == []


def test_a_lane_may_renew_its_own_claim() -> None:
    """The single writer for a lane is still that lane; this is not a collision."""
    lanes = {"1-1": {"worktree": "/tmp/a", "branch": "feat/a", "status": "working"}}
    audit = isolation.audit_claim(lanes, "1-1", worktree="/tmp/a", branch="feat/a")
    assert audit.ok


@pytest.mark.parametrize("status", sorted(isolation.RELEASED_STATUSES))
def test_a_released_lane_frees_its_worktree(status: str) -> None:
    """Closeout must be able to hand a worktree to the next run."""
    lanes = {"1-1": {"worktree": "/tmp/a", "branch": "feat/a", "status": status}}
    audit = isolation.audit_claim(lanes, "1-2", worktree="/tmp/a", branch="feat/b")
    assert audit.ok


def test_a_closed_lane_may_reclaim_its_own_old_worktree() -> None:
    lanes = {"1-1": {"worktree": "/tmp/a", "branch": "feat/a", "status": "closed"}}
    audit = isolation.audit_claim(lanes, "1-1", worktree="/tmp/a", branch="feat/a2")
    assert audit.ok


def test_claiming_neither_worktree_nor_branch_is_refused() -> None:
    """An unclaimed lane is not an isolated lane."""
    audit = isolation.audit_claim({}, "1-1")
    assert not audit.ok
    with pytest.raises(isolation.LaneCollisionError):
        isolation.claim_lane({}, "1-1")


def test_claiming_only_a_branch_is_allowed() -> None:
    """A researcher may hold a branch without a worktree of its own."""
    audit = isolation.audit_claim({}, "1-3", branch="feat/research")
    assert audit.ok


def test_the_audit_reports_every_violation_at_once() -> None:
    """Both failures at once, so one fix round resolves the dispatch."""
    lanes = {"1-1": {"worktree": "/tmp/a", "branch": "feat/a", "status": "working"}}
    audit = isolation.audit_claim(lanes, "1-2", worktree="/tmp/a", branch="feat/a")
    assert len(audit.violations) == 2


def test_audit_payload_is_serialisable_and_names_the_holder() -> None:
    lanes = {"1-1": {"worktree": "/tmp/a", "branch": "feat/a", "status": "working"}}
    audit = isolation.audit_claim(lanes, "1-2", worktree="/tmp/a", branch="feat/b")
    payload = audit.as_dict()
    assert payload["ok"] is False
    assert payload["lane"] == "1-2"
    assert payload["existing_claims"][0]["lane"] == "1-1"
    assert payload["violations"]


@pytest.mark.parametrize("status", ["orphaned", "recovery_required", "unknown"])
def test_unverified_terminal_state_keeps_the_claim(status: str) -> None:
    """Loss of observability is not proof that the worker released its resources."""
    lanes = {"1-1": {"worktree": "/tmp/a", "branch": "feat/a", "status": status}}
    audit = isolation.audit_claim(lanes, "1-2", worktree="/tmp/a")
    assert not audit.ok


def test_status_matching_is_case_insensitive() -> None:
    lanes = {"1-1": {"worktree": "/tmp/a", "branch": "feat/a", "status": "CLOSED"}}
    assert isolation.audit_claim(lanes, "1-2", worktree="/tmp/a").ok


# --------------------------------------------------------------------------
# Closeout Lifecycle Gate — ordering
# --------------------------------------------------------------------------


def test_closeout_steps_are_in_the_canonical_order() -> None:
    assert gate.CLOSEOUT_STEPS == (
        "docs_aligned",
        "child_pushed",
        "parent_pointer_updated",
        "pr_merged",
        "worktree_removed",
    )


def test_a_fully_satisfied_lane_may_close() -> None:
    report = gate.evaluate_closeout("1-1", gate.SATISFIED_EVIDENCE)
    assert report.allowed
    assert report.pane_close_allowed
    assert report.blocked_at == ""


def test_worktree_removal_is_the_only_destructive_step() -> None:
    """It is last, and nothing else in the ladder destroys anything."""
    assert gate.DESTRUCTIVE_STEPS == {"worktree_removed"}
    assert gate.CLOSEOUT_STEPS[-1] == "worktree_removed"


# --------------------------------------------------------------------------
# Closeout Lifecycle Gate — the premature-destruction cases
# --------------------------------------------------------------------------


def test_unpushed_child_blocks_closeout_and_pane_close() -> None:
    """Lesson 5: closing here silently drops the child push."""
    evidence = {k: dict(v) for k, v in gate.SATISFIED_EVIDENCE.items()}
    evidence["child_pushed"] = {"branch_pushed": False, "remote_contains_head": False}

    report = gate.evaluate_closeout("1-1", evidence)
    assert not report.allowed
    assert not report.pane_close_allowed
    assert report.blocked_at == "child_pushed"


def test_unmerged_pr_blocks_closeout() -> None:
    evidence = {k: dict(v) for k, v in gate.SATISFIED_EVIDENCE.items()}
    evidence["pr_merged"] = {"pr_merged": False, "default_branch_contains_head": False}

    report = gate.evaluate_closeout("1-1", evidence)
    assert not report.allowed
    assert report.blocked_at == "pr_merged"


def test_a_stale_parent_pointer_blocks_closeout() -> None:
    evidence = {k: dict(v) for k, v in gate.SATISFIED_EVIDENCE.items()}
    evidence["parent_pointer_updated"] = {"pointer_at_pushed_commit": False}
    assert gate.evaluate_closeout("1-1", evidence).blocked_at == "parent_pointer_updated"


def test_a_surviving_worktree_blocks_closeout() -> None:
    evidence = {k: dict(v) for k, v in gate.SATISFIED_EVIDENCE.items()}
    evidence["worktree_removed"] = {"worktree_absent": False}
    report = gate.evaluate_closeout("1-1", evidence)
    assert not report.allowed
    assert report.blocked_at == "worktree_removed"


def test_a_partial_evidence_bundle_blocks_rather_than_passing() -> None:
    """Fail loud: an unproven step is not a passed step."""
    report = gate.evaluate_closeout("1-1", {"docs_aligned": {"docs_reconciled": True}})
    assert not report.allowed
    assert report.blocked_at == "child_pushed"


def test_no_evidence_at_all_blocks_everything() -> None:
    report = gate.evaluate_closeout("1-1")
    assert not report.allowed
    assert report.blocked_at == "docs_aligned"
    assert len(report.steps) == len(gate.CLOSEOUT_STEPS)


def test_a_later_step_is_never_reported_broken_when_an_earlier_one_is() -> None:
    """Ordering must not tell anyone to delete a worktree that was never pushed.

    An unpushed child also means the worktree still exists, but the *reason*
    to fix it is the push. Reporting both as independent failures sends the
    reader to the wrong step.
    """
    report = gate.evaluate_closeout("1-1", {})
    worktree = report.result_for("worktree_removed")
    assert worktree is not None
    assert not worktree.passed
    assert "not reached" in worktree.detail


def test_evaluating_without_early_stop_still_blocks() -> None:
    report = gate.evaluate_closeout("1-1", {}, stop_at_first_failure=False)
    assert not report.allowed
    assert all(not r.passed for r in report.steps)


def test_assert_closeout_raises_with_a_readable_report() -> None:
    with pytest.raises(gate.CloseoutGateError) as excinfo:
        gate.assert_closeout_allowed("1-1", {})
    rendered = str(excinfo.value)
    assert "gate CLOSED at docs_aligned" in rendered
    assert "1-1" in rendered


def test_assert_closeout_returns_the_report_when_satisfied() -> None:
    report = gate.assert_closeout_allowed("1-1", gate.SATISFIED_EVIDENCE)
    assert report.allowed


def test_unknown_step_is_refused() -> None:
    result = gate.evaluate_step("teleport_done", {"ok": True})
    assert not result.passed
    assert "unknown closeout step" in result.detail


def test_step_detail_names_the_missing_fact() -> None:
    result = gate.evaluate_step("child_pushed", {"branch_pushed": True})
    assert not result.passed
    assert "remote_contains_head" in result.detail


def test_every_required_fact_must_be_true() -> None:
    result = gate.evaluate_step("child_pushed", {"branch_pushed": False, "remote_contains_head": True})
    assert not result.passed
    assert "branch_pushed" in result.detail


def test_report_render_lists_every_step_in_order() -> None:
    report = gate.evaluate_closeout("1-2", {})
    rendered = report.render()
    positions = [rendered.index(step) for step in gate.CLOSEOUT_STEPS]
    assert positions == sorted(positions)
    assert "[BLOCK]" in rendered


def test_report_render_shows_the_open_gate() -> None:
    rendered = gate.evaluate_closeout("1-2", gate.SATISFIED_EVIDENCE).render()
    assert "gate OPEN" in rendered


def test_report_serialises_for_a_sidebar_or_a_handoff() -> None:
    payload = gate.evaluate_closeout("1-1", {}).as_dict()
    assert payload["lane"] == "1-1"
    assert payload["allowed"] is False
    assert len(payload["steps"]) == len(gate.CLOSEOUT_STEPS)
    assert payload["steps"][0]["step"] == "docs_aligned"


def test_result_for_returns_none_for_an_unlisted_step() -> None:
    assert gate.evaluate_closeout("1-1", {}).result_for("nope") is None


def test_satisfied_evidence_covers_every_step() -> None:
    """A drifted fixture would silently weaken the gate's own tests."""
    assert set(gate.SATISFIED_EVIDENCE) == set(gate.CLOSEOUT_STEPS)
    for step, facts in gate.SATISFIED_EVIDENCE.items():
        assert set(facts) == set(gate.STEP_FACTS[step]), step


# --------------------------------------------------------------------------
# Plugin CLI surface
# --------------------------------------------------------------------------


@pytest.fixture()
def state_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway git repo holding a dispatch state file."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "dispatch").mkdir()
    return repo


def _write_state(repo: Path, lanes: dict) -> None:
    state = brain.default_state()
    state["lanes"] = lanes
    brain.save(brain.state_path(repo), state)


def test_claim_command_exits_two_on_a_collision(state_repo: Path, capsys) -> None:
    """The contract's assertion: a shared worktree is refused with exit 2."""
    _write_state(state_repo, {"1-1": {"worktree": "/tmp/shared", "branch": "feat/a"}})
    code = plugin.main(
        ["--repo", str(state_repo), "claim", "--lane", "1-2",
         "--worktree", "/tmp/shared", "--branch", "feat/b"]
    )
    assert code == plugin.EXIT_GATE_REFUSED
    assert "already claimed by live lane" in capsys.readouterr().err


def test_claim_command_succeeds_for_an_independent_lane(state_repo: Path) -> None:
    _write_state(state_repo, {"1-1": {"worktree": "/tmp/a", "branch": "feat/a"}})
    code = plugin.main(
        ["--repo", str(state_repo), "claim", "--lane", "1-2",
         "--worktree", "/tmp/b", "--branch", "feat/b"]
    )
    assert code == 0


def test_claim_json_output_names_the_holding_lane(state_repo: Path, capsys) -> None:
    import json

    _write_state(state_repo, {"1-1": {"worktree": "/tmp/a", "branch": "feat/a"}})
    plugin.main(
        ["--repo", str(state_repo), "claim", "--lane", "1-2",
         "--worktree", "/tmp/a", "--branch", "feat/b", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["existing_claims"][0]["lane"] == "1-1"


def test_closeout_command_blocks_an_unpushed_lane(state_repo: Path, capsys) -> None:
    code = plugin.main(["--repo", str(state_repo), "closeout", "--lane", "1-1"])
    assert code == plugin.EXIT_GATE_REFUSED
    assert "gate CLOSED" in capsys.readouterr().out


def test_closeout_command_opens_on_full_evidence(state_repo: Path, capsys) -> None:
    import json

    code = plugin.main(
        ["--repo", str(state_repo), "closeout", "--lane", "1-1",
         "--evidence", json.dumps(gate.SATISFIED_EVIDENCE)]
    )
    assert code == 0
    assert "gate OPEN" in capsys.readouterr().out


def test_closeout_command_rejects_malformed_evidence(state_repo: Path, capsys) -> None:
    code = plugin.main(
        ["--repo", str(state_repo), "closeout", "--lane", "1-1", "--evidence", "{not json"]
    )
    assert code == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_closeout_command_rejects_non_object_evidence(state_repo: Path, capsys) -> None:
    code = plugin.main(
        ["--repo", str(state_repo), "closeout", "--lane", "1-1", "--evidence", "[1,2]"]
    )
    assert code == 2
    assert "must be a JSON object" in capsys.readouterr().err


def _code_lines(path: Path) -> list[str]:
    """Source lines with docstrings and comments removed.

    Both gate modules *document* the commands they refuse to run. A substring
    scan over raw text therefore flags the prohibition as a violation, which is
    the failure mode the single-writer gate already solved by parsing the AST.
    Judging code rather than prose about code keeps these assertions meaningful
    instead of forcing the docs to be worded around them.
    """
    import ast

    text = path.read_text(encoding="utf-8")
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

    out = []
    for no, raw in enumerate(text.splitlines(), start=1):
        if no in skip:
            continue
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


def test_the_plugin_never_destroys_a_pane_itself() -> None:
    """The gate authorises destruction; performing it is someone else's job.

    A gate that both decides and acts cannot be the thing that audits it, and
    this is the exact seam where the premature-pane-destruction lesson lives.

    Asserted on *execution*, not wording: the plugin legitimately prints "pane
    close are permitted" when reporting an open gate, and a text scan would flag
    the report as the offence.
    """
    code = "\n".join(_code_lines(BIN / "dispatch_plugin.py"))
    assert "pane_close" not in code
    # An argv array is how every Herdr call in this plugin is shaped, so a close
    # would have to appear as a consecutive token pair.
    assert '"pane", "close"' not in code
    assert "'pane', 'close'" not in code


def test_closeout_gate_never_runs_the_destructive_commands() -> None:
    """The gate is pure policy: it decides, and shells out to nothing.

    Without this, "allowed" could quietly grow a side effect and the gate would
    be both the decision and the actor.
    """
    code = "\n".join(_code_lines(LIB / "closeout_gate.py"))
    assert "subprocess" not in code
    assert "run_herdr" not in code
    assert "os.system" not in code


def test_isolation_module_never_creates_a_worktree() -> None:
    """It decides whether a claim is legal; provisioning stays with Herdr."""
    code = "\n".join(_code_lines(LIB / "lane_isolation.py"))
    assert "subprocess" not in code
    assert "run_herdr" not in code
    assert '"worktree", "create"' not in code


# --------------------------------------------------------------------------
# Manifest wiring
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest() -> dict:
    import tomllib

    with (PLUGIN_ROOT / "herdr-plugin.toml").open("rb") as handle:
        return tomllib.load(handle)


# The gates are CLI pipeline tools, not menu entries. See the NOTE in
# herdr-plugin.toml for the full reasoning; this pins the decision so the
# actions cannot quietly creep back into the palette.
FORBIDDEN_MANIFEST_ACTIONS = frozenset({"claim", "closeout", "prompt-check", "notify"})


def test_manifest_does_not_expose_the_pipeline_gates(manifest: dict) -> None:
    """A manifest command gets no runtime arguments, so these cannot work.

    `claim` needs `--lane`, `closeout` needs an evidence bundle, `prompt-check`
    needs stdin. Herdr reports exit 0 for a launch regardless, so a gate that
    always refuses would look healthy in the menu while being unusable.
    """
    ids = {entry["id"] for entry in manifest.get("actions", [])}
    assert not (ids & FORBIDDEN_MANIFEST_ACTIONS), sorted(ids & FORBIDDEN_MANIFEST_ACTIONS)


def _required_flags(subcommand: str) -> list[str]:
    """Flags the plugin CLI cannot run without, for one subcommand."""
    parser = plugin.build_parser()
    for action in parser._subparsers._group_actions:  # noqa: SLF001
        if not hasattr(action, "choices") or subcommand not in action.choices:
            continue
        sub = action.choices[subcommand]
        return [
            opt
            for act in sub._actions  # noqa: SLF001
            for opt in act.option_strings
            if getattr(act, "required", False)
        ]
    return []


def test_every_declared_action_is_runnable_without_arguments(manifest: dict) -> None:
    """The structural form of the rule, checked against the real argparse tree.

    Reading the parser rather than pattern-matching the source means this keeps
    working when the CLI changes shape, and it catches the failure whatever it
    is called: an action whose subcommand has a required flag is dead on
    arrival, because a manifest command is a fixed argv array.
    """
    for entry in manifest.get("actions", []):
        command = entry["command"]
        script_at = next(
            i for i, part in enumerate(command) if part.endswith("dispatch_plugin.py")
        )
        subcommand = command[script_at + 1]
        required = _required_flags(subcommand)
        assert not required, (
            f"action {entry['id']!r} runs `{subcommand}`, which requires "
            f"{required}; a manifest action cannot supply arguments"
        )


def test_pipeline_gates_remain_available_on_the_cli() -> None:
    """Removing them from the palette must not remove them from the CLI."""
    out = subprocess.run(
        [sys.executable, str(BIN / "dispatch_plugin.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    for sub in ("claim", "closeout", "prompt", "notify", "guard"):
        assert sub in out.stdout, sub