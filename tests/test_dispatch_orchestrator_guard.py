"""Tests for the orchestrator permission gate and the Issue #125 lint contract.

The gate exists because the orchestrator can ruin a lane without touching a
lane's files: probing git status, re-reading child code, polling panes. That is
work the worker was dispatched to do, and doing it as the orchestrator produces
the false-busywork loop and child-work takeover.

A whitelist that is never exercised with a violating input is a comment, not a
gate, so the matrix below is tested in both directions for every phase.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

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
guard_mod = _load("dispatch_orchestrator_guard", LIB / "orchestrator_guard.py")
plugin = _load("dispatch_plugin", BIN / "dispatch_plugin.py")
brain = _load("dispatch_orchestrator_state", LIB / "orchestrator_state.py")

ALL_PHASES = list(guard_mod.BRAIN_PHASES)


@pytest.fixture(autouse=True)
def _no_live_herdr(monkeypatch: pytest.MonkeyPatch):
    def refuse(*args, **kwargs):
        raise AssertionError("test attempted a live Herdr call; patch plugin.herdr.run_herdr")

    monkeypatch.setattr(plugin.herdr, "run_herdr", refuse)


# --------------------------------------------------------------------------
# The matrix covers every brain phase
# --------------------------------------------------------------------------


def test_guard_covers_all_seven_brain_phases() -> None:
    assert len(ALL_PHASES) == 7
    assert set(ALL_PHASES) == set(brain.BRAIN_PHASES), "guard drifted from the state machine"
    assert set(guard_mod.PHASE_ALLOWANCES) == set(ALL_PHASES)


def test_an_unknown_phase_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown brain phase"):
        guard_mod.OrchestratorGuard("vibes")


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_every_phase_has_a_whitelist(phase: str) -> None:
    assert guard_mod.allowed_in(phase), phase


@pytest.mark.parametrize("phase", ALL_PHASES)
@pytest.mark.parametrize("probe", sorted(guard_mod.FORBIDDEN_PROBES))
def test_probes_are_refused_in_every_phase(phase: str, probe: str) -> None:
    """49 combinations. A probe allowed in even one phase is the loophole."""
    verdict = guard_mod.OrchestratorGuard(phase).evaluate(probe)
    assert not verdict.allowed, f"{probe} permitted in {phase}"
    assert "child-work takeover" in verdict.reason


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_an_invented_probe_name_is_refused_by_default(phase: str) -> None:
    """Matching the whole `probe_*` family means new names need no registration."""
    assert not guard_mod.OrchestratorGuard(phase).permits("probe_anything_at_all")


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_every_phase_allows_the_read_only_basics(phase: str) -> None:
    guard = guard_mod.OrchestratorGuard(phase)
    for action in guard_mod.ALWAYS_ALLOWED:
        assert guard.permits(action), f"{action} blocked in {phase}"


@pytest.mark.parametrize(
    ("phase", "allowed_action"),
    [
        ("contract", "lint_task_contract"),
        ("topology", "dispatch_lane"),
        ("yield_and_guard", "wait_lanes"),
        ("synthesis", "reconcile_facts"),
        ("decision", "spawn_skeptic"),
        ("human_gate", "await_human"),
        ("closed", "read_state"),
    ],
)
def test_each_phase_permits_its_own_actions(phase: str, allowed_action: str) -> None:
    assert guard_mod.OrchestratorGuard(phase).permits(allowed_action)


@pytest.mark.parametrize(
    ("phase", "forbidden_action"),
    [
        ("contract", "dispatch_lane"),
        ("topology", "reconcile_facts"),
        ("yield_and_guard", "dispatch_lane"),
        ("synthesis", "spawn_skeptic"),
        ("decision", "dispatch_lane"),
        ("human_gate", "reconcile_facts"),
        ("closed", "dispatch_lane"),
    ],
)
def test_each_phase_refuses_another_phase_s_actions(phase: str, forbidden_action: str) -> None:
    assert not guard_mod.OrchestratorGuard(phase).permits(forbidden_action)


# --------------------------------------------------------------------------
# The park is a hard stop
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    ["probe_git_status", "probe_child_code", "dispatch_lane", "claim_lane", "git_push"],
)
def test_parked_orchestrator_refuses_non_wake_actions(action: str) -> None:
    guard = guard_mod.OrchestratorGuard("yield_and_guard")
    with pytest.raises(guard_mod.IllegalOrchestratorActionError) as excinfo:
        guard.check(action)
    assert excinfo.value.phase == "yield_and_guard"
    assert excinfo.value.action == action


def test_parked_orchestrator_accepts_a_wake_signal() -> None:
    verdict = guard_mod.OrchestratorGuard("yield_and_guard", wake_signal="notify").check("wake")
    assert verdict.allowed


def test_a_todo_reminder_is_not_a_wake_signal() -> None:
    """The false-busywork loop, closed at the gate rather than by asking nicely."""
    guard = guard_mod.OrchestratorGuard("yield_and_guard", wake_signal="todo_reminder")
    with pytest.raises(guard_mod.IllegalOrchestratorActionError, match="is not a wake signal"):
        guard.check("wake")


@pytest.mark.parametrize("signal", ["notify", "stall_alarm", "human"])
def test_each_recognised_wake_signal_is_accepted(signal: str) -> None:
    guard = guard_mod.OrchestratorGuard("yield_and_guard", wake_signal=signal)
    assert guard.check("wake").allowed


def test_no_supplied_signal_still_allows_waking_out_of_the_park() -> None:
    """An unqualified wake is the default path; a *wrong* signal is the problem."""
    assert guard_mod.OrchestratorGuard("yield_and_guard").check("wake").allowed


@pytest.mark.parametrize("phase", [p for p in ALL_PHASES if p != "yield_and_guard"])
def test_wake_is_refused_when_not_parked(phase: str) -> None:
    """A wake signal with nothing to wake is the orchestrator talking to itself."""
    assert not guard_mod.OrchestratorGuard(phase).permits("wake")


# --------------------------------------------------------------------------
# Human gate
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action", ["git_push", "merge_pr", "delete_branch", "remove_worktree", "close_pane"]
)
def test_publication_is_refused_without_human_authorisation(action: str) -> None:
    """Irreversible work belongs to the human, never to an automatic path."""
    verdict = guard_mod.OrchestratorGuard("human_gate").evaluate(action)
    assert not verdict.allowed
    assert "human authorisation" in verdict.reason


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_publication_is_refused_everywhere_except_nowhere(phase: str) -> None:
    assert not guard_mod.OrchestratorGuard(phase).permits("git_push")


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def test_verdict_serialises() -> None:
    payload = guard_mod.OrchestratorGuard("yield_and_guard").evaluate("probe_git_status").as_dict()
    assert payload["allowed"] is False
    assert payload["action"] == "probe_git_status"
    assert "wake" in payload["allowed_actions"]


def test_verdict_render_shows_what_would_be_allowed() -> None:
    rendered = guard_mod.OrchestratorGuard("yield_and_guard").evaluate("dispatch_lane").render()
    assert "REFUSE dispatch_lane" in rendered
    assert "permitted here:" in rendered
    assert "wake" in rendered


def test_allowed_verdict_render_is_short() -> None:
    assert "ALLOW" in guard_mod.OrchestratorGuard("topology").evaluate("dispatch_lane").render()


def test_evaluate_never_raises_and_check_always_does() -> None:
    guard = guard_mod.OrchestratorGuard("closed")
    assert guard.evaluate("dispatch_lane").allowed is False
    with pytest.raises(guard_mod.IllegalOrchestratorActionError):
        guard.check("dispatch_lane")


def test_functional_shorthand() -> None:
    assert guard_mod.check_action("topology", "dispatch_lane").allowed
    with pytest.raises(guard_mod.IllegalOrchestratorActionError):
        guard_mod.check_action("topology", "probe_child_code")


def test_matrix_is_exported_as_data() -> None:
    rows = guard_mod.matrix()
    assert [row["phase"] for row in rows] == ALL_PHASES
    assert all(row["allowed"] for row in rows)


def test_allowed_actions_is_sorted_and_stable() -> None:
    guard = guard_mod.OrchestratorGuard("yield_and_guard")
    assert guard.allowed_actions() == guard.allowed_actions()
    assert guard.allowed_actions() == sorted(guard.allowed_actions())


# --------------------------------------------------------------------------
# The gate judges; it never acts
# --------------------------------------------------------------------------


def test_guard_runs_nothing_itself() -> None:
    """Decides and refuses; the caller performs the action it allowed.

    A guard that also does the work cannot be the thing that audits the work.
    """
    code = "\n".join(_code_lines(LIB / "orchestrator_guard.py"))
    assert "subprocess" not in code
    assert "run_herdr" not in code
    assert "os.system" not in code


def _code_lines(path: Path) -> list[str]:
    """Source lines with docstrings and comments removed.

    This module's docstring *explains* that it never advances the brain, so a
    raw text scan would flag the explanation as the violation.
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

    return [
        line
        for no, line in enumerate(text.splitlines(), start=1)
        if no not in skip and line.strip() and not line.strip().startswith("#")
    ]


def test_guard_never_advances_the_brain_on_its_own() -> None:
    """It refuses; transitioning the phase is the orchestrator's decision."""
    code = "\n".join(_code_lines(LIB / "orchestrator_guard.py"))
    assert "import orchestrator_state" not in code
    assert ".advance(" not in code
    assert "import brain" not in code


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BIN / "dispatch_plugin.py"), *args],
        capture_output=True, text=True,
    )


def test_cli_allows_a_legal_action() -> None:
    proc = _run(["guard", "--phase", "topology", "--action", "dispatch_lane"])
    assert proc.returncode == 0
    assert "ALLOW" in proc.stdout


def test_cli_refuses_a_probe_with_exit_2() -> None:
    proc = _run(["guard", "--phase", "yield_and_guard", "--action", "probe_git_status"])
    assert proc.returncode == plugin.EXIT_GATE_REFUSED
    assert "REFUSE" in proc.stderr


def test_cli_json_output() -> None:
    proc = _run(["guard", "--phase", "closed", "--action", "dispatch_lane", "--json"])
    payload = json.loads(proc.stdout)
    assert payload["allowed"] is False
    assert payload["phase"] == "closed"


def test_cli_lists_the_whitelist() -> None:
    proc = _run(["guard", "--phase", "yield_and_guard", "--list"])
    assert proc.returncode == 0
    assert "wake" in json.loads(proc.stdout)["allowed"]


def test_cli_rejects_an_unknown_phase() -> None:
    proc = _run(["guard", "--phase", "vibes", "--action", "wake"])
    assert proc.returncode == plugin.EXIT_GATE_REFUSED
    assert "unknown brain phase" in proc.stderr


def test_cli_reads_the_phase_from_the_state_file(tmp_path: Path) -> None:
    """Police the brain as it is, not as the caller believes it to be."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "dispatch").mkdir()
    state = brain.default_state()
    state["orchestrator_phase"] = "yield_and_guard"
    brain.save(brain.state_path(repo), state)

    proc = _run(["--repo", str(repo), "guard", "--action", "probe_git_status"])
    assert proc.returncode == plugin.EXIT_GATE_REFUSED
    assert "yield_and_guard" in proc.stderr


def test_guard_is_not_a_manifest_action() -> None:
    """It takes --action, which a manifest command cannot supply."""
    import tomllib

    with (PLUGIN_ROOT / "herdr-plugin.toml").open("rb") as handle:
        manifest = tomllib.load(handle)
    assert "guard" not in {entry["id"] for entry in manifest.get("actions", [])}


# ==========================================================================
# Gate A (Issue #133): PreToolUse reflex gate — anti-takeover
# ==========================================================================
#
# The whitelist above polices a *named orchestrator step*. A tool call is not
# a named step: the orchestrator can reach a worker's file with `read_file` and
# never appear in the action matrix at all. Gate A closes that hole at the tool
# boundary, in three layers ordered by cost:
#
#   1. whitelist bypass  — management reads pass locally, no model call
#   2. mechanical refuse — a business-code probe while parked is a fact
#   3. Jev semantics     — the genuinely ambiguous call gets a Noul judgment
#
# The order matters: paying a model call to learn that `git reset --hard` in a
# canonical root checkout is destructive would be spending tokens on a fact.


def test_gate_a_is_exported() -> None:
    for name in (
        "TOOL_WHITELIST",
        "BUSINESS_CODE_TOOLS",
        "PROBE_TOOLS",
        "GateAVerdict",
        "GateAReport",
        "is_management_call",
        "is_business_code_path",
        "check_tool_call",
        "THRESHOLD_ROLE_BOUNDARY",
        "THRESHOLD_ILLEGAL_PROBE",
    ):
        assert hasattr(guard_mod, name), f"Gate A is missing {name}"


def test_gate_a_threshold_is_the_issue_value() -> None:
    assert guard_mod.THRESHOLD_ROLE_BOUNDARY == 0.40
    assert guard_mod.THRESHOLD_ILLEGAL_PROBE == 0.40


# -- 1. fast whitelist bypass ---------------------------------------------


@pytest.mark.parametrize(
    ("tool", "target"),
    [
        ("todo", ""),
        ("todowrite", ""),
        ("read_file", ".git/dispatch/ORCHESTRATOR_STATE.json"),
        ("read_file", "~/Documents/handoffs/1-5-gate-a-handoff-20261001_234002.md"),
        ("read_file", "~/Documents/handoffs/"),
        ("read_file", "/tmp/handoff/1-5-gate-a-handoff.md"),
        ("read_file", ".dispatch_task_gate_a_anti_takeover.md"),
        ("bash", "python3 bin/dispatch_plugin.py status"),
        ("bash", "python3 bin/dispatch_plugin.py render_board"),
        ("bash", "python3 bin/dispatch_plugin.py harvest"),
    ],
)
def test_gate_a_whitelists_management_reads_while_parked(tool: str, target: str) -> None:
    report = guard_mod.check_tool_call(
        tool, target=target, phase="yield_and_guard", use_jev=False
    )
    assert report.allowed, report.render()
    assert report.verdict is guard_mod.GateAVerdict.WHITELISTED


def test_gate_a_whitelist_bypass_never_calls_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """<1ms local放行: a whitelisted call must not open a socket at all."""

    def refuse(*args, **kwargs):
        raise AssertionError("whitelist bypass attempted a model call")

    monkeypatch.setattr(guard_mod, "_ask_jev", refuse)
    monkeypatch.setenv("TYPESAFE_API_KEY", "placeholder")
    report = guard_mod.check_tool_call(
        "read_file", target=".git/dispatch/ORCHESTRATOR_STATE.json", phase="yield_and_guard"
    )
    assert report.allowed
    assert report.model == "whitelist"


def test_gate_a_whitelist_is_not_a_hole_for_business_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A management *command* cannot smuggle a business-code path past the gate."""
    monkeypatch.setattr(guard_mod, "_ask_jev", lambda *a, **k: None)
    report = guard_mod.check_tool_call(
        "bash",
        command="cat .worktrees/feat-lane/src/app.py",
        phase="yield_and_guard",
        use_jev=False,
    )
    assert not report.allowed
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_CHILD_CODE


# -- 2. mechanical hard interception while parked ---------------------------


@pytest.mark.parametrize(
    "tool", ["read_file", "write_file", "replace_file_content", "view_file"]
)
def test_gate_a_refuses_business_code_reads_while_parked(tool: str) -> None:
    report = guard_mod.check_tool_call(
        tool,
        target=".worktrees/feat-gate-a-anti-takeover/template/lib/orchestrator_guard.py",
        phase="yield_and_guard",
        use_jev=False,
    )
    assert not report.allowed
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_CHILD_CODE
    assert "parked" in report.reason


@pytest.mark.parametrize("phase", [p for p in ALL_PHASES if p != "yield_and_guard"])
def test_gate_a_park_is_the_only_phase_that_refuses_business_code(phase: str) -> None:
    """Reading source in synthesis is legitimate reconciliation, not takeover."""
    report = guard_mod.check_tool_call(
        "read_file", target="src/parser.py", phase=phase, use_jev=False
    )
    assert report.allowed, report.render()


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git -C .worktrees/feat-lane diff",
        "pytest tests/test_worker.py",
        "cat src/app.py",
        "grep -rn TODO src/",
        "ls -la .worktrees/feat-lane",
    ],
)
def test_gate_a_refuses_probes_while_parked(command: str) -> None:
    report = guard_mod.check_tool_call(
        "bash", command=command, phase="yield_and_guard", use_jev=False
    )
    assert not report.allowed
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_PROBE
    assert "child-work takeover" in report.reason


def test_gate_a_probe_in_another_phase_is_still_refused() -> None:
    """A probe is a probe in every phase; the park is only where it is fatal."""
    report = guard_mod.check_tool_call(
        "bash", command="git status", phase="synthesis", use_jev=False
    )
    assert not report.allowed


def test_gate_a_parked_orchestrator_may_still_read_its_own_docs() -> None:
    report = guard_mod.check_tool_call(
        "read_file", target="CONTEXT.md", phase="yield_and_guard", use_jev=False
    )
    assert report.allowed


@pytest.mark.parametrize(
    ("command", "target"),
    [
        # A destructive command is a fact whichever argument carries it, so it
        # has to be judged whichever argument carries it.
        ("git reset --hard", ""),
        ("", "git reset --hard"),
        # Both set: `command or target` picks one, so the *other* must still be
        # judged. Otherwise putting the destructive text in `target` while
        # `command` holds something innocuous is a free pass.
        ("python3 -m pip list", "git reset --hard"),
        ("git reset --hard", "python3 -m pip list"),
        ("cat ~/Documents/handoffs/plan.md && git reset --hard", ""),
        # One argument carrying both a marker and the destruction: the marker
        # must not vouch for the rest of its own line.
        (
            "python3 -m pip list",
            "cat ~/Documents/handoffs/x.md && git reset --hard",
        ),
        ("", "python3 bin/dispatch_plugin.py status && git clean -fd"),
        ("dispatch_plugin.py status; git reset --hard origin/main", ""),
    ],
)
def test_gate_a_whitelist_never_bypasses_root_protection(command: str, target: str) -> None:
    """A management read cannot buy a destructive command.

    This is the composition the per-layer tests do not catch on their own: each
    layer is individually correct, and reading the management whitelist first
    would let a leading legitimate path carry a trailing `git reset --hard`
    straight through. The 增补令 admits no exception, so the mechanical check has
    to run before the bypass.
    """
    report = guard_mod.check_tool_call(
        "bash",
        command=command,
        target=target,
        cwd="/srv/orch/work/config/mac-bootstrap",
        phase="topology",
        use_jev=False,
    )
    assert not report.allowed, f"{command!r} / {target!r} slipped past the root gate"
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_ROOT_DESTRUCTIVE
    assert report.model == guard_mod.MECHANICAL_MODEL


def test_gate_a_whitelist_never_bypasses_the_park_refusal() -> None:
    """The same composition, for the business-code rule."""
    report = guard_mod.check_tool_call(
        "bash",
        command="cat ~/Documents/handoffs/x.md && cat .worktrees/1-4/src/app.py",
        phase="yield_and_guard",
        use_jev=False,
    )
    assert not report.allowed
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_CHILD_CODE


def test_gate_a_isolation_is_not_defeated_by_a_parent_traversal() -> None:
    """`/worktrees/../config` is the root checkout wearing a worktree's name.

    Resolving the path before matching is what makes the boundary mean
    something; a substring test on the raw string would not.
    """
    for cwd in [
        "/srv/orch/work/config/mac-bootstrap/.worktrees/../config/mac-bootstrap",
        "/srv/orch/.herdr/worktrees/../../work/config/mac-bootstrap",
    ]:
        assert not guard_mod.is_isolated_worktree(cwd), cwd
        report = guard_mod.check_tool_call(
            "bash", command="git reset --hard", cwd=cwd, phase="topology", use_jev=False
        )
        assert not report.allowed, cwd
        assert report.verdict is guard_mod.GateAVerdict.REFUSE_ROOT_DESTRUCTIVE


def test_gate_a_isolation_still_permits_a_real_worktree_path() -> None:
    """The traversal check must not also refuse a genuine worktree."""
    for cwd in [
        "/srv/orch/work/config/mac-bootstrap/.worktrees/feat-auth",
        "/srv/orch/.herdr/worktrees/mac-bootstrap/feat-gate-a",
    ]:
        assert guard_mod.is_isolated_worktree(cwd), cwd


def test_gate_a_isolation_of_a_path_that_does_not_exist() -> None:
    """The lane worktree may not exist yet; a refusal here would be a crash."""
    assert guard_mod.is_isolated_worktree("/nonexistent/.worktrees/feat-auth")
    assert not guard_mod.is_isolated_worktree("/nonexistent/repo")
    assert not guard_mod.is_isolated_worktree("")


@pytest.mark.parametrize(
    "target",
    [
        # A marker is a substring, so `..` walks straight out of the directory it
        # named. The whitelist is a bypass, and a bypass that can be walked out of
        # is not one.
        "/srv/orch/repo/.dispatch/../src/app.py",
        "~/Documents/handoffs/../../../src/app.py",
        "/srv/orch/repo/.dispatch/../../.worktrees/1-4/src/app.py",
    ],
)
def test_gate_a_whitelist_marker_cannot_be_walked_out_of(target: str) -> None:
    report = guard_mod.check_tool_call(
        "read_file", target=target, phase="yield_and_guard", use_jev=False
    )
    assert not report.allowed, f"{target!r} was whitelisted"
    assert report.verdict is not guard_mod.GateAVerdict.WHITELISTED


def test_gate_a_whitelist_marker_still_allows_a_real_management_read() -> None:
    """The traversal check must not cost the bypass its legitimate cases."""
    for target in [
        "/srv/orch/repo/.dispatch/TASK.md",
        "/srv/orch/.herdr/worktrees/mac-bootstrap/feat-a/.dispatch/TASK.md",
    ]:
        assert guard_mod.is_management_call("read_file", target=target), target


def test_gate_a_a_marker_in_target_cannot_vouch_for_a_lane_read_in_command() -> None:
    """Both arguments are judged; neither is a character vouching for the other.

    The disqualifiers used to live only on the command branch, so a marker in
    `target` short-circuited them entirely.
    """
    report = guard_mod.check_tool_call(
        "bash",
        target="~/Documents/handoffs/x.md",
        command="cat .worktrees/1-4/src/app.py",
        phase="yield_and_guard",
        use_jev=False,
    )
    assert not report.allowed
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_CHILD_CODE


@pytest.mark.parametrize(
    "command",
    [
        # `git -C` names the tree to operate on, so a worktree cwd does not make
        # the target a worktree.
        "git -C /srv/orch/work/config/mac-bootstrap clean -fdx",
        "git -C /srv/orch/work/config/mac-bootstrap reset --hard",
        "git --git-dir /srv/orch/work/config/mac-bootstrap/.git clean -fd",
        "git -C/srv/orch/work/config/mac-bootstrap checkout .",
        "git -C /srv/orch/work/config/mac-bootstrap/.git checkout .",
    ],
)
def test_gate_a_a_destructive_command_naming_a_root_is_refused(command: str) -> None:
    """Isolation is judged from the command's *target*, not only from the cwd.

    A worktree cwd plus a `git -C <root>` is a root checkout reached through the
    back door, and it is the exact shape a lane produces by accident. Refused from
    a worktree cwd as well, because the command overrides where it runs.
    """
    for cwd in ["/srv/orch/.herdr/worktrees/mac-bootstrap/feat-a", ""]:
        report = guard_mod.check_tool_call(
            "bash", command=command, cwd=cwd, phase="topology", use_jev=False
        )
        assert not report.allowed, f"{command!r} permitted from cwd={cwd!r}"
        assert report.verdict is guard_mod.GateAVerdict.REFUSE_ROOT_DESTRUCTIVE


@pytest.mark.parametrize(
    "command",
    [
        # Long forms and the modern spellings of the same destruction. These are
        # refused in a root checkout and permitted in a lane's own worktree, which
        # is the whole point of the boundary — so the permission is asserted too.
        "git switch --discard-changes",
        "rm --recursive --force src/",
        "git worktree remove .worktrees/1-4",
    ],
)
def test_gate_a_long_form_destruction_obeys_the_isolation_boundary(command: str) -> None:
    """A gate that knows only `-rf` is one refactor away from failing.

    Both the refusal in a root and the permission in a worktree are asserted: a
    gate that refuses everywhere would train people to route around it, which is
    a failure that looks like success.
    """
    for cwd in ["/srv/orch/work/config/mac-bootstrap", ""]:
        report = guard_mod.check_tool_call(
            "bash", command=command, cwd=cwd, phase="topology", use_jev=False
        )
        assert not report.allowed, f"{command!r} permitted from cwd={cwd!r}"
        assert report.verdict is guard_mod.GateAVerdict.REFUSE_ROOT_DESTRUCTIVE

    inside = guard_mod.check_tool_call(
        "bash",
        command=command,
        cwd="/srv/orch/repo/.worktrees/feat-auth",
        phase="topology",
        use_jev=False,
    )
    assert inside.allowed, f"{command!r} refused inside a lane worktree: {inside.render()}"


def test_gate_a_git_c_into_a_worktree_is_still_permitted() -> None:
    """The widened check must not refuse a lane operating inside its own tree."""
    report = guard_mod.check_tool_call(
        "bash",
        command="git -C /srv/orch/repo/.worktrees/feat-auth clean -fd",
        cwd="/srv/orch/repo/.worktrees/feat-auth",
        phase="topology",
        use_jev=False,
    )
    assert report.allowed, report.render()


@pytest.mark.parametrize("tool", ["read", "open_file", "fs_read", "some_future_reader", ""])
def test_gate_a_a_tool_name_this_gate_has_not_heard_of_is_still_judged(tool: str) -> None:
    """The parked business-code rule is about the *path*, not the tool's name.

    Gating it on a known tool list means renaming `read_file` to `read` turns the
    rule off, which is the failure mode a whitelist of names always has.
    """
    report = guard_mod.check_tool_call(
        tool,
        target=".worktrees/1-4/src/app.py",
        phase="yield_and_guard",
        use_jev=False,
    )
    assert not report.allowed, f"tool {tool!r} read a lane's source while parked"


@pytest.mark.parametrize("tool", ["read", "open_file", "fs_read", ""])
def test_gate_a_ordinary_source_read_while_parked_is_business_code(tool: str) -> None:
    """Deliberately *not* a lane worktree path.

    That isolates the generic source rule from the lane-code rule above, and it is
    the case a tool-name gate lets through.
    """
    report = guard_mod.check_tool_call(
        tool, target="src/parser.py", phase="yield_and_guard", use_jev=False
    )
    assert not report.allowed, f"tool {tool!r} read source while parked"
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_CHILD_CODE


@pytest.mark.parametrize("tool", ["read_file", "read", ""])
def test_gate_a_the_same_read_outside_the_park_is_allowed(tool: str) -> None:
    """Guards the other direction: reading source in synthesis is reconciliation.

    A gate that refuses correct work is worse than no gate, and that failure looks
    exactly like a gate working.
    """
    report = guard_mod.check_tool_call(tool, target="src/parser.py", phase="synthesis", use_jev=False)
    assert report.allowed, report.render()


def test_gate_a_an_unrecognised_tool_naming_a_lane_worktree_path_is_refused() -> None:
    report = guard_mod.check_tool_call(
        "some_future_shell",
        command="cat .worktrees/1-4/src/app.py",
        phase="yield_and_guard",
        use_jev=False,
    )
    assert not report.allowed
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_CHILD_CODE
    # The reason must name the lane worktree, not merely "a source file": the two
    # rules refuse alike, and only one of them tells the orchestrator what it
    # actually reached for.
    assert "lane worktree" in report.reason


def test_gate_a_a_non_finite_noul_cannot_read_as_a_pass() -> None:
    """`nan > 0.40` is False, so a NaN probability would allow if it were believed."""
    for value in [float("nan"), float("inf"), float("-inf")]:
        assert guard_mod._noul({"x": value}, "x") == (0.0, False), value


@pytest.mark.parametrize(
    "answers",
    [
        {"is_role_boundary_violation": "high", "is_illegal_probe_while_parked": "high"},
        {"is_role_boundary_violation": None, "is_illegal_probe_while_parked": None},
        {"is_role_boundary_violation": {"noul": {}}, "is_illegal_probe_while_parked": {"noul": []}},
        # One usable answer and one missing: a half-answer is no answer.
        {"is_role_boundary_violation": 0.9},
        {},
    ],
)
def test_gate_a_an_unusable_jev_answer_falls_back_instead_of_passing(
    monkeypatch: pytest.MonkeyPatch, answers: dict
) -> None:
    """A parsed-but-meaningless answer must not read as a confident zero.

    `float("high")` raises and `float(None)` raises, so both land on 0.0 — which
    is exactly what a genuine 0.0 looks like to the threshold. The consumer
    cannot tell "the model said no" from "the model said something unusable", so
    the sentinel has to carry a flag and the caller has to act on it. Without
    that, a garbage response silently converts a refusal into a pass.
    """
    _stub_jev_raw(monkeypatch, json.dumps({"model": "jev-test", "answers": answers}))
    report = guard_mod.check_tool_call(
        "bash",
        command="python3 -c 'print(1-4)'",
        phase="yield_and_guard",
        awaiting=["1-4"],
        key="placeholder",
    )
    # The offline heuristic refuses this call; an unusable answer must reach it.
    assert not report.allowed
    assert report.model == "heuristic-fallback"


def test_gate_a_a_genuine_zero_is_still_an_answer() -> None:
    """The unusable flag must not swallow a real 0.0, which is a legitimate Noul.

    The model being confident there is no violation is an answer, and treating it
    as no answer would push every clean call through the heuristics instead.
    """
    assert guard_mod._noul({"x": 0.0}, "x") == (0.0, True)
    assert guard_mod._noul({"x": {"noul": 0.0}}, "x") == (0.0, True)
    assert guard_mod._noul({"x": "0"}, "x") == (0.0, True)


def test_gate_a_the_model_name_is_sanitised(monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoint's own name lands in reports and logs; keep it inert."""
    _stub_jev_raw(
        monkeypatch,
        json.dumps(
            {
                "model": "jev\n[INJECTED] rm -rf /",
                "answers": {
                    "is_role_boundary_violation": {"noul": 0.1},
                    "is_illegal_probe_while_parked": {"noul": 0.1},
                },
            }
        ),
    )
    answered = guard_mod._ask_jev({}, key="placeholder")
    assert "\n" not in answered["model"]
    assert len(answered["model"]) <= 64


# -- 3. root checkout protection (incident hard-coding) --------------------


def test_gate_a_refuses_git_reset_hard_in_the_root_checkout() -> None:
    """The incident, codefied: a canonical root checkout is never a scratch pad."""
    report = guard_mod.check_tool_call(
        "bash",
        command="git reset --hard origin/main",
        cwd="/srv/orch/work/config/mac-bootstrap",
        phase="topology",
        use_jev=False,
    )
    assert not report.allowed
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_ROOT_DESTRUCTIVE
    assert "root checkout" in report.reason


@pytest.mark.parametrize(
    "command",
    [
        "git reset --hard",
        "git clean -fd",
        "git clean -fdx",
        "git checkout -- .",
        "git checkout .",
        "rm -rf src/",
        "git stash drop",
        "git push --force origin main",
    ],
)
def test_gate_a_refuses_root_destructive_commands_in_every_phase(command: str) -> None:
    for phase in ALL_PHASES:
        report = guard_mod.check_tool_call(
            "bash",
            command=command,
            cwd="/srv/orch/work/projects/auroraops-control",
            phase=phase,
            use_jev=False,
        )
        assert not report.allowed, f"{command!r} permitted in {phase}"
        assert report.verdict is guard_mod.GateAVerdict.REFUSE_ROOT_DESTRUCTIVE


def test_gate_a_refuses_root_destructive_in_a_submodule_root() -> None:
    """主子模块根目录 counts as a canonical root, not as a lane."""
    report = guard_mod.check_tool_call(
        "bash",
        command="git reset --hard",
        cwd="/srv/orch/work/config/mac-bootstrap/template",
        phase="contract",
        use_jev=False,
    )
    assert not report.allowed
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_ROOT_DESTRUCTIVE


def test_gate_a_permits_destructive_commands_inside_a_lane_worktree() -> None:
    """A lane may reset its own scratch worktree; that is the isolation boundary."""
    report = guard_mod.check_tool_call(
        "bash",
        command="git reset --hard",
        cwd="/srv/orch/.herdr/worktrees/mac-bootstrap/feat-gate-a-anti-takeover",
        phase="topology",
        use_jev=False,
    )
    assert report.allowed, report.render()


def test_gate_a_permits_destructive_commands_inside_dot_worktrees() -> None:
    report = guard_mod.check_tool_call(
        "bash",
        command="git clean -fd",
        cwd="/srv/orch/work/config/mac-bootstrap/.worktrees/feat-auth",
        phase="topology",
        use_jev=False,
    )
    assert report.allowed, report.render()


def test_gate_a_root_protection_applies_outside_the_park() -> None:
    """`yield_and_guard` is not the only thing standing between a reset and a lost day."""
    report = guard_mod.check_tool_call(
        "bash", command="git reset --hard", cwd="/srv/orch/work", phase="contract", use_jev=False
    )
    assert not report.allowed


def test_gate_a_read_only_git_is_not_a_root_destructive_refusal() -> None:
    """Protection is about destroying the tree, not about reading it.

    A read-only `git status` in the root checkout is still a probe, and the probe
    rule is deliberately phase-independent — that is existing guard behaviour,
    not something the incident changed. What the incident added is narrower: the
    read is never refused *as a destructive root command*, so dropping the cwd
    never changes the reason.
    """
    for command in ("git status", "git diff --stat", "git log --oneline -3"):
        report = guard_mod.check_tool_call(
            "bash", command=command, cwd="/srv/orch/work/config/mac-bootstrap",
            phase="topology", use_jev=False,
        )
        assert report.verdict is not guard_mod.GateAVerdict.REFUSE_ROOT_DESTRUCTIVE, command
        assert not guard_mod.is_root_destructive(command)


def test_gate_a_read_only_git_outside_the_park_is_still_a_probe() -> None:
    """The probe rule did not change; only the root-destructive rule is new.

    Stated explicitly so a future reader does not assume the incident widened
    into a blanket ban on reading the orchestrator's own repository.
    """
    report = guard_mod.check_tool_call(
        "bash", command="git log --oneline -3", phase="topology", use_jev=False
    )
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_PROBE


# -- 4. Jev semantic layer --------------------------------------------------


def _jev(**answers: float):
    """A raw TypeSafe System One response carrying the given Noul probabilities."""
    return {
        "model": "jev-test",
        "answers": {k: {"type": "noul", "noul": v} for k, v in answers.items()},
    }


def _stub_jev(monkeypatch: pytest.MonkeyPatch, **answers: float) -> dict:
    """Replace the network call with a stub, returning the state it was handed.

    Goes through the real normaliser rather than fabricating the gate's internal
    shape, so a rename in `_ask_jev` fails these tests instead of quietly passing
    a hand-made dict that no production path ever produces.
    """
    seen: dict = {}

    def fake_urlopen(request, timeout=None):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        payload = json.dumps(_jev(**answers)).encode("utf-8")
        response = MagicMock()
        response.read.return_value = payload
        return MagicMock(__enter__=lambda _self: response, __exit__=lambda *a: False)

    monkeypatch.setattr(guard_mod.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_gate_a_jev_request_carries_both_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One batched round trip, both Noul questions, nothing conversational."""
    seen = _stub_jev(monkeypatch, is_role_boundary_violation=0.1, is_illegal_probe_while_parked=0.1)
    guard_mod.check_tool_call(
        "bash", command="python3 -m pip list", phase="yield_and_guard", key="placeholder"
    )
    questions = seen["body"]["questions"]
    assert set(questions) == {"is_role_boundary_violation", "is_illegal_probe_while_parked"}
    assert all(entry["type"] == "noul" for entry in questions.values())
    assert seen["body"]["state"]["tool"] == "bash"
    assert seen["body"]["state"]["phase"] == "yield_and_guard"


def _stub_jev_raw(monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    """Replace the network call with one returning an arbitrary raw body."""

    def fake_urlopen(request, timeout=None):
        response = MagicMock()
        response.read.return_value = body.encode("utf-8")
        return MagicMock(__enter__=lambda _self: response, __exit__=lambda *a: False)

    monkeypatch.setattr(guard_mod.urllib.request, "urlopen", fake_urlopen)


@pytest.mark.parametrize(
    "body",
    [
        "not json at all",
        "[1, 2, 3]",  # valid JSON, wrong shape
        '{"answers": "nope"}',
        '{"model": "jev-test"}',  # no answers key
    ],
)
def test_gate_a_jev_degrades_to_heuristics_on_a_malformed_answer(
    monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    """An endpoint that answers with nonsense must not be read as a pass.

    Every one of these has the same requirement: no usable judgment, so the
    offline layer decides. Returning `None` here is what makes the gate fall
    back rather than trust a zero.
    """
    _stub_jev_raw(monkeypatch, body)
    assert guard_mod._ask_jev({}, key="placeholder") is None

    report = guard_mod.check_tool_call(
        "bash",
        command="python3 -c 'print(1-4)'",
        phase="yield_and_guard",
        awaiting=["1-4"],
        key="placeholder",
    )
    assert report.model == "heuristic-fallback"


def test_gate_a_jev_degrades_on_a_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request, timeout=None):
        raise OSError("Network unreachable")

    monkeypatch.setattr(guard_mod.urllib.request, "urlopen", refuse)
    assert guard_mod._ask_jev({}, key="placeholder") is None


@pytest.mark.parametrize(
    ("value", "expected", "usable"),
    [
        (0.91, 0.91, True),
        ({"noul": 0.91}, 0.91, True),
        ({"noul": "0.91"}, 0.91, True),
        # Bounded: a probability outside [0, 1] is not usable evidence.
        (7.0, 1.0, True),
        (-1.0, 0.0, True),
        # Unusable. 0.0 is returned as a placeholder, but `usable` is False, so
        # the caller falls back rather than reading it as a confident pass.
        ({"noul": None}, 0.0, False),
        ({"noul": "not a number"}, 0.0, False),
        ("not a number", 0.0, False),
        (None, 0.0, False),
        (float("nan"), 0.0, False),
        (float("inf"), 0.0, False),
        (True, 0.0, False),
    ],
)
def test_gate_a_reads_a_noul_however_the_endpoint_spells_it(
    monkeypatch: pytest.MonkeyPatch, value: object, expected: float, usable: bool
) -> None:
    """A bare number, a wrapped one, a numeric string — all the same answer.

    The endpoint's exact spelling is not something this gate should depend on;
    the *usability* is, because it decides whether the offline layer gets a say.
    """
    assert guard_mod._noul({"x": value}, "x") == (pytest.approx(expected), usable)

    _stub_jev_raw(
        monkeypatch,
        json.dumps(
            {
                "model": "jev-test",
                "answers": {
                    "is_role_boundary_violation": value,
                    "is_illegal_probe_while_parked": 0.1,
                },
            }
        ),
    )
    answered = guard_mod._ask_jev({}, key="placeholder")
    if usable:
        assert answered is not None
        assert answered["p_role_boundary_violation"] == pytest.approx(expected)
    else:
        assert answered is None, "an unusable answer must route to the heuristics"


def test_gate_a_jev_defaults_the_model_name_when_the_endpoint_omits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_jev_raw(
        monkeypatch,
        json.dumps(
            {
                "answers": {
                    "is_role_boundary_violation": {"noul": 0.1},
                    "is_illegal_probe_while_parked": {"noul": 0.1},
                }
            }
        ),
    )
    answered = guard_mod._ask_jev({}, key="placeholder")
    assert answered["model"] == guard_mod.DEFAULT_JEV_MODEL


def test_gate_a_explicit_empty_key_forces_the_offline_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit empty string is the documented way to skip the network."""

    def refuse(*args, **kwargs):
        raise AssertionError("an explicit empty key still reached the network")

    monkeypatch.setattr(guard_mod, "_ask_jev", refuse)
    monkeypatch.setenv("TYPESAFE_API_KEY", "placeholder")
    report = guard_mod.check_tool_call(
        "bash", command="python3 -m pip list", phase="yield_and_guard", key=""
    )
    assert report.model == "heuristic-fallback"


def test_gate_a_explicit_key_beats_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_jev(monkeypatch, is_role_boundary_violation=0.1, is_illegal_probe_while_parked=0.1)
    monkeypatch.setenv("TYPESAFE_API_KEY", "from-the-environment")
    assert guard_mod.resolve_api_key("explicit") == "explicit"
    assert guard_mod.resolve_api_key(None) == "from-the-environment"


def test_gate_a_reads_the_key_from_the_omp_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The omp session keeps its key in its own env file, not in this process.

    Without this the gate is silently offline in the one environment it is
    actually meant to run in — which fails open, so it is worth pinning.
    """
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    omp_env = tmp_path / ".omp" / "agent" / ".env"
    omp_env.parent.mkdir(parents=True)
    omp_env.write_text("OTHER=x\nTYPESAFE_API_KEY=from-omp-env\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert guard_mod.resolve_api_key() == "from-omp-env"


def test_gate_a_an_unreadable_omp_env_file_is_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A permissions problem resolves to offline, not to a traceback."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    def refuse(self, *args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "read_text", refuse)
    assert guard_mod.resolve_api_key() == ""


@pytest.mark.parametrize(
    ("p_role", "p_probe", "blocked"),
    [
        (0.41, 0.00, True),  # role alone blocks
        (0.00, 0.41, True),  # probe alone blocks
        (0.40, 0.00, False),  # exactly at the line does not
        (0.00, 0.40, False),
        (0.00, 0.00, False),
    ],
)
def test_gate_a_either_signal_alone_blocks_at_the_line(
    monkeypatch: pytest.MonkeyPatch, p_role: float, p_probe: float, blocked: bool
) -> None:
    """The two questions are independent; neither is a prerequisite for the other.

    The boundary is strict: 0.40 is the issue's stated line and reads as allowed,
    so a calibrated model returning exactly the threshold is not blocked.
    """
    _stub_jev(
        monkeypatch,
        is_role_boundary_violation=p_role,
        is_illegal_probe_while_parked=p_probe,
    )
    report = guard_mod.check_tool_call(
        "webfetch", target="https://example.com/1-4", phase="yield_and_guard", key="placeholder"
    )
    assert report.allowed is not blocked
    if blocked:
        assert report.verdict is guard_mod.GateAVerdict.REFUSE_SEMANTIC


def test_gate_a_jev_blocks_a_role_boundary_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ambiguous case Jev exists for: no probe verb, no source suffix, parked.

    `webfetch` on an internal service URL names no file and reads no tree, so
    neither mechanical layer can settle it. Whether it is the worker doing its
    job through a side channel is a question of role, and that is a judgment.
    """
    _stub_jev(monkeypatch, is_role_boundary_violation=0.71, is_illegal_probe_while_parked=0.05)
    report = guard_mod.check_tool_call(
        "webfetch",
        target="https://internal.example/ledger/1-4",
        phase="yield_and_guard",
        key="placeholder",
    )
    assert not report.allowed
    assert report.verdict is guard_mod.GateAVerdict.REFUSE_SEMANTIC
    assert report.p_role_boundary_violation == 0.71
    assert report.p_illegal_probe_while_parked == 0.05
    assert report.corrective_steer, "a semantic refusal must carry a steer"


def test_gate_a_jev_blocks_an_illegal_probe_while_parked(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_jev(monkeypatch, is_role_boundary_violation=0.10, is_illegal_probe_while_parked=0.66)
    report = guard_mod.check_tool_call(
        "bash",
        command="python3 -c 'import lane_state'",
        phase="yield_and_guard",
        key="placeholder",
    )
    assert not report.allowed
    assert report.p_illegal_probe_while_parked == 0.66
    assert report.corrective_steer


def test_gate_a_jev_allows_a_below_threshold_call(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_jev(monkeypatch, is_role_boundary_violation=0.20, is_illegal_probe_while_parked=0.05)
    report = guard_mod.check_tool_call(
        "bash",
        command="python3 -m pip list",
        phase="yield_and_guard",
        key="placeholder",
    )
    assert report.allowed
    assert report.verdict is guard_mod.GateAVerdict.ALLOW
    assert report.model == "jev-test"


def test_gate_a_jev_never_asked_about_a_mechanical_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Facts do not get a second opinion from a model."""

    def refuse(*args, **kwargs):
        raise AssertionError("a mechanical refusal must not reach Jev")

    monkeypatch.setattr(guard_mod, "_ask_jev", refuse)
    monkeypatch.setenv("TYPESAFE_API_KEY", "placeholder")
    report = guard_mod.check_tool_call(
        "read_file", target=".worktrees/feat-lane/src/app.py", phase="yield_and_guard"
    )
    assert not report.allowed
    assert report.model == "mechanical"


def test_gate_a_jev_falls_back_to_heuristics_when_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreachable Jev is not a pass; the offline layer decides."""
    monkeypatch.setattr(guard_mod, "_ask_jev", lambda state, **kwargs: None)
    report = guard_mod.check_tool_call(
        "bash",
        command="python3 -c 'print(1-4)'",
        phase="yield_and_guard",
        awaiting=["1-4"],
        key="placeholder",
    )
    assert not report.allowed
    assert report.model == "heuristic-fallback"
    assert report.p_illegal_probe_while_parked > guard_mod.THRESHOLD_ILLEGAL_PROBE


def test_gate_a_offline_default_is_the_deterministic_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same wiring lesson as Gate C: heuristics are the baseline, not the exception."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/nonexistent-home")))
    report = guard_mod.check_tool_call(
        "bash",
        command="python3 -c 'print(1-4)'",
        phase="yield_and_guard",
        awaiting=["1-4"],
    )
    assert not report.allowed
    assert report.model == "heuristic-fallback"


def test_gate_a_offline_allows_an_ordinary_call_with_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Degradation must not become a blanket refusal."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/nonexistent-home")))
    report = guard_mod.check_tool_call(
        "bash", command="python3 -m pip list", phase="yield_and_guard"
    )
    assert report.allowed, report.render()
    assert report.model == "heuristic-fallback"


# -- 5. the report ----------------------------------------------------------


def test_gate_a_report_serialises() -> None:
    report = guard_mod.check_tool_call(
        "read_file", target=".worktrees/x/src/a.py", phase="yield_and_guard", use_jev=False
    )
    payload = report.as_dict()
    assert payload["allowed"] is False
    assert payload["verdict"] == guard_mod.GateAVerdict.REFUSE_CHILD_CODE.value
    assert payload["tool"] == "read_file"
    assert payload["phase"] == "yield_and_guard"


def test_gate_a_refusal_render_names_the_remedy() -> None:
    report = guard_mod.check_tool_call(
        "read_file", target=".worktrees/x/src/a.py", phase="yield_and_guard", use_jev=False
    )
    rendered = report.render()
    assert "REFUSE" in rendered
    assert "parked" in rendered


def test_gate_a_check_raises_and_evaluate_does_not() -> None:
    gate = guard_mod.ToolCallGate("yield_and_guard", use_jev=False)
    assert gate.evaluate("read_file", target=".worktrees/x/src/a.py").allowed is False
    with pytest.raises(guard_mod.IllegalOrchestratorActionError):
        gate.check("read_file", target=".worktrees/x/src/a.py")


def test_gate_a_gate_judges_and_does_not_act() -> None:
    """The interceptor blocks a tool call; it never performs one."""
    code = "\n".join(_code_lines(LIB / "orchestrator_guard.py"))
    assert "subprocess" not in code
    assert "os.system" not in code


# -- 6. CLI -----------------------------------------------------------------


def _run_tool(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BIN / "dispatch_plugin.py"), *args],
        capture_output=True, text=True,
    )


def test_cli_gate_a_blocks_a_parked_business_code_read(tmp_path: Path) -> None:
    proc = _run_tool(
        [
            "gate",
            "--phase", "yield_and_guard",
            "--tool", "read_file",
            "--target", ".worktrees/feat-lane/src/app.py",
        ]
    )
    assert proc.returncode == plugin.EXIT_GATE_REFUSED
    assert "REFUSE" in proc.stderr


def test_cli_gate_a_allows_a_management_read(tmp_path: Path) -> None:
    proc = _run_tool(
        [
            "gate",
            "--phase", "yield_and_guard",
            "--tool", "read_file",
            "--target", ".git/dispatch/ORCHESTRATOR_STATE.json",
            "--json",
        ]
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["allowed"] is True


def test_cli_gate_a_blocks_a_root_reset_hard() -> None:
    proc = _run_tool(
        [
            "gate",
            "--phase", "topology",
            "--tool", "bash",
            "--command", "git reset --hard origin/main",
            "--cwd", "/srv/orch/work/config/mac-bootstrap",
        ]
    )
    assert proc.returncode == plugin.EXIT_GATE_REFUSED
    assert "root checkout" in proc.stderr


def test_cli_gate_a_is_not_a_manifest_action() -> None:
    """It needs a tool name and a target, which a manifest command cannot supply."""
    import tomllib

    with (PLUGIN_ROOT / "herdr-plugin.toml").open("rb") as handle:
        manifest = tomllib.load(handle)
    assert "gate" not in {entry["id"] for entry in manifest.get("actions", [])}


# -- 7. the OMP extension ---------------------------------------------------


def _load_ts_source(name: str) -> str:
    return (
        REPO_ROOT / "agent" / "omp" / "extensions" / "dispatch-omp" / f"{name}.ts"
    ).read_text(encoding="utf-8")


def test_omp_reflex_gate_is_wired_into_tool_call() -> None:
    """A gate nobody calls is a comment. The hook must be registered."""
    source = _load_ts_source("index")
    assert "reflexGate" in source
    assert '"tool_call"' in source


def test_omp_reflex_gate_never_blocks_a_subagent() -> None:
    source = _load_ts_source("reflex")
    assert "isRoot" in source or "hasUI" in source


def test_reflex_gate_ts_file_exists() -> None:
    assert (REPO_ROOT / "agent" / "omp" / "extensions" / "dispatch-omp" / "reflex.ts").is_file()