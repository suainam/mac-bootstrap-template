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