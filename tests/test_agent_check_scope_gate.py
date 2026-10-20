"""Tests for the docs-only shortcut in the repository/machine check gate."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "agent_check_scope_gate.py"


def run_gate(
    scope: str, tmp_path: Path, event: object, *, python: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["AGENT_RUNTIME_REPO_ROOT"] = str(tmp_path)
    env["AGENT_RUNTIME_PYTHON"] = str(python or Path(sys.executable))
    env["AGENT_RUNTIME_EVENT_JSON"] = (
        event if isinstance(event, str) else json.dumps(event)
    )
    return subprocess.run(
        [sys.executable, str(GATE), scope],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def write_makefile(tmp_path: Path, marker: Path) -> None:
    (tmp_path / "Makefile").write_text(
        f"repo-check:\n\t@touch {marker}\nmachine-check:\n\t@touch {marker}\n",
        encoding="utf-8",
    )


def test_documentation_only_push_skips_repository_check(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    write_makefile(tmp_path, marker)

    result = run_gate("repository", tmp_path, {"target_paths": ["docs/notes.md", "README.md"]})

    assert result.returncode == 0, result.stderr
    assert "documentation only" in result.stderr
    assert not marker.exists()


def test_documentation_only_push_skips_machine_check(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    write_makefile(tmp_path, marker)
    policy = tmp_path / "policy"
    policy.write_text("[agent \"runtime\"]\n\tmanagementCheckout = true\n", encoding="utf-8")
    env_policy = policy

    env = os.environ.copy()
    env.update(
        AGENT_RUNTIME_REPO_ROOT=str(tmp_path),
        AGENT_RUNTIME_PYTHON=sys.executable,
        AGENT_RUNTIME_POLICY_CONFIG=str(env_policy),
        AGENT_RUNTIME_EVENT_JSON=json.dumps({"target_paths": ["docs/a.md"]}),
    )
    result = subprocess.run(
        [sys.executable, str(GATE), "machine"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "documentation only" in result.stderr
    assert not marker.exists()


def test_mixed_push_still_runs_repository_check(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    write_makefile(tmp_path, marker)

    result = run_gate(
        "repository", tmp_path, {"target_paths": ["docs/notes.md", "scripts/gate.py"]}
    )

    assert result.returncode == 0, result.stderr
    assert marker.exists()


def test_empty_or_malformed_event_never_skips(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    write_makefile(tmp_path, marker)

    for event in ({"target_paths": []}, {"target_paths": ["docs/a.md", ""]}, "{not json"):
        marker.unlink(missing_ok=True)
        result = run_gate("repository", tmp_path, event)
        assert result.returncode == 0, result.stderr
        assert marker.exists(), event
