"""Tests for the single-writer invariant gate — TB-02.

The gate's job is to fail the build on the three forbidden writes. A gate that
only ever passes is worse than no gate, so most of these tests deliberately feed
it violating input.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = REPO_ROOT / "scripts" / "dispatch-single-writer-gate.py"

spec = importlib.util.spec_from_file_location("dispatch_single_writer_gate", GATE_PATH)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)


# --------------------------------------------------------------------------
# Rule 1: no semantic agent-state reporting
# --------------------------------------------------------------------------


def test_detects_semantic_state_report_ts() -> None:
    violations = gate.scan_text(
        'send({ method: "pane.report_agent", params: { state } });\n',
        "ext.ts",
    )
    assert [v.rule for v in violations] == ["semantic-state-report"]


def test_detects_semantic_state_report_python() -> None:
    violations = gate.scan_text(
        'req("pane.report_agent", {"pane_id": p, "state": "working"})\n', "tool.py"
    )
    assert violations and violations[0].rule == "semantic-state-report"


def test_detects_hand_rolled_state_payload() -> None:
    """Building the payload by hand is the same write by another route."""
    violations = gate.scan_text('payload = {"state": "blocked"}\n', "tool.py")
    assert violations and violations[0].rule == "semantic-state-report"


def test_detects_cli_report_agent_spelling() -> None:
    """The CLI wrapper must not be an escape hatch.

    `herdr pane report-agent` is the documented command for the same write as
    `pane.report_agent`. A gate matching only the socket spelling would pass on
    code that uses the CLI.
    """
    violations = gate.scan_text(
        'run_herdr(["pane", "report-agent", pane, "--state", "working"])\n', "tool.py"
    )
    assert violations and violations[0].rule == "semantic-state-report"


def test_report_agent_session_cli_spelling_is_allowed() -> None:
    assert gate.scan_text(
        'run_herdr(["pane", "report-agent-session", pane])\n', "tool.py"
    ) == []


def test_report_metadata_is_allowed() -> None:
    """Presentation metadata is the *sanctioned* write, not the forbidden one."""
    assert gate.scan_text('req("pane.report_metadata", {"tokens": {}})\n', "ext.ts") == []


def test_report_agent_session_is_allowed() -> None:
    """A session reference is not a lifecycle report."""
    assert gate.scan_text('req("pane.report_agent_session", {"pane_id": p})\n', "ext.ts") == []


def test_reading_agent_status_is_allowed() -> None:
    assert gate.scan_text('status = agent["agent_status"]\n', "watchdog.py") == []


# --------------------------------------------------------------------------
# Rule 2: no edits to Herdr-managed integration files
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "herdr-omp-agent-state.ts",
        "herdr-claude-agent-state.sh",
        "herdr-codex-agent-session.py",
    ],
)
def test_detects_managed_integration_reference(name: str) -> None:
    violations = gate.scan_text(f'open("~/.omp/agent/extensions/{name}", "w")\n', "t.py")
    assert violations and violations[0].rule == "managed-integration-edit"


def test_dispatch_extension_file_is_allowed() -> None:
    assert gate.scan_text('import "herdr-dispatch/index.ts"\n', "t.ts") == []


# --------------------------------------------------------------------------
# Rule 3: dispatch must not attach its own resume command (skeptic S-12)
# --------------------------------------------------------------------------


def test_detects_self_resume_argv() -> None:
    violations = gate.scan_text('report["resume_argv"] = argv\n', "t.py")
    assert violations and violations[0].rule == "self-resume-argv"


# --------------------------------------------------------------------------
# Comments and blanks must not trigger
# --------------------------------------------------------------------------


def test_comments_are_ignored() -> None:
    text = (
        "# we deliberately do not call pane.report_agent here\n"
        '// pane.report_agent is owned by herdr:omp\n'
        "<!-- pane.report_agent -->\n"
        "\n"
    )
    assert gate.scan_text(text, "t.py") == []


def test_docstrings_may_explain_the_rule() -> None:
    """Prose about the forbidden call is not the forbidden call."""
    text = (
        'def report_lane_metadata(pane_id):\n'
        '    """Publish a lane\'s tokens.\n'
        '    Never pane.report_agent: herdr:omp owns lifecycle state.\n'
        '    """\n'
        '    return run_herdr(["pane", "report-metadata", pane_id])\n'
    )
    assert gate.scan_text(text, "tool.py") == []


def test_code_after_a_docstring_is_still_checked() -> None:
    """Docstring skipping must not blind the gate to real code."""
    text = (
        'def bad(pane_id):\n'
        '    """Docstring mentioning pane.report_agent.\n'
        '    More prose here.\n'
        '    """\n'
        '    return run_herdr(["pane", "report-agent", pane_id])\n'
    )
    violations = gate.scan_text(text, "tool.py")
    assert len(violations) == 1
    assert violations[0].line_no == 5


def test_shipped_state_module_is_clean() -> None:
    """The TB-01 store must not trip its own gate."""
    store = REPO_ROOT / "multiplexer" / "herdr-dispatch" / "lib" / "orchestrator_state.py"
    assert gate.scan_text(store.read_text(encoding="utf-8"), store.name) == []


# --------------------------------------------------------------------------
# Repo-level behaviour
# --------------------------------------------------------------------------


def test_repo_passes_its_own_gate() -> None:
    assert gate.scan_repo(REPO_ROOT) == []


def test_missing_owned_paths_pass_vacuously(tmp_path: Path) -> None:
    """Before the plugin exists there is nothing to violate; that is not a failure."""
    assert gate.scan_repo(tmp_path, ("multiplexer/herdr-dispatch",)) == []


def test_violating_fixture_fails_with_location(tmp_path: Path) -> None:
    """The negative test the ticket demands: a real violation must be caught."""
    owned = tmp_path / "multiplexer" / "herdr-dispatch"
    owned.mkdir(parents=True)
    (owned / "bad.ts").write_text(
        'const r = await send("pane.report_agent", { state: "working" });\n'
    )
    (owned / "good.ts").write_text('await send("pane.report_metadata", {});\n')

    violations = gate.scan_repo(tmp_path, ("multiplexer/herdr-dispatch",))
    assert len(violations) == 1
    assert violations[0].path == "multiplexer/herdr-dispatch/bad.ts"
    assert violations[0].line_no == 1
    assert violations[0].rule == "semantic-state-report"
    assert "herdr:omp" in violations[0].guidance


def test_cli_exit_codes(tmp_path: Path, capsys) -> None:
    clean = tmp_path / "multiplexer" / "herdr-dispatch"
    clean.mkdir(parents=True)
    (clean / "ok.ts").write_text('send("pane.report_metadata", {});\n')
    assert gate.main(["--root", str(tmp_path)]) == 0
    capsys.readouterr()

    (clean / "bad.ts").write_text('send("pane.report_agent", {});\n')
    assert gate.main(["--root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "single-writer invariant violated" in err
    assert "herdr.dev" in err


def test_cli_accepts_owned_path_override(tmp_path: Path) -> None:
    elsewhere = tmp_path / "custom" / "dir"
    elsewhere.mkdir(parents=True)
    (elsewhere / "bad.py").write_text('send("pane.report_agent", {})\n')
    assert gate.scan_repo(tmp_path, ("multiplexer/herdr-dispatch",)) == []
    assert len(gate.scan_repo(tmp_path, ("custom/dir",))) == 1


def test_node_modules_and_venv_are_skipped(tmp_path: Path) -> None:
    owned = tmp_path / "multiplexer" / "herdr-dispatch"
    for sub in ("node_modules", "__pycache__", ".venv"):
        target = owned / sub
        target.mkdir(parents=True)
        (target / "bad.ts").write_text('send("pane.report_agent", {})\n')
    assert gate.scan_repo(tmp_path, ("multiplexer/herdr-dispatch",)) == []