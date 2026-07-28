from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Sequence

import pytest


ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = ROOT / "scripts" / "agent_git_hook_dispatcher.py"
RUNTIME = ROOT / "scripts" / "agent_runtime.py"
REGISTRY = ROOT / "agent" / "runtime" / "registry.jsonc"


def clean_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "PYTHON",
        "PYTHON_BIN",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "QUALITY_GATES_BYPASS",
        "QUALITY_GATES_BYPASS_REASON",
    ):
        env.pop(key, None)
    env["HOME"] = str(home)
    env["XDG_STATE_HOME"] = str(home / ".local" / "state")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    return env


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(env),
        input=input_text,
        capture_output=True,
        text=True,
        check=check,
    )


def git(
    repo: Path,
    env: Mapping[str, str],
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=repo, env=env, check=check)


def init_repo(repo: Path, env: Mapping[str, str]) -> None:
    repo.mkdir(parents=True)
    git(repo, env, "init", "-q", "-b", "main")
    git(repo, env, "config", "user.email", "template-profile@example.com")
    git(repo, env, "config", "user.name", "Template Profile Test")
    (repo / "sample.py").write_text("def original():\n    return 1\n", encoding="utf-8")
    git(repo, env, "add", "sample.py")
    git(repo, env, "commit", "-qm", "initial")


def dispatcher(
    repo: Path,
    home: Path,
    install_root: Path,
    state_root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run(
        [
            sys.executable,
            str(DISPATCHER),
            "--repo",
            str(repo),
            "--install-root",
            str(install_root),
            "--state-root",
            str(state_root),
            "--python",
            sys.executable,
            *args,
        ],
        cwd=repo,
        env=clean_env(home),
        check=check,
    )


@pytest.mark.parametrize(
    "profile",
    ["mac-bootstrap-template", "python-repo-smoke"],
)
def test_python_repository_profile_migrates_commit_push_and_rolls_back(
    tmp_path: Path,
    profile: str,
):
    home = tmp_path / "home"
    home.mkdir()
    env = clean_env(home)
    repo_marker = tmp_path / "repo-checks.txt"
    machine_marker = tmp_path / "machine-checks.txt"
    env["AGENT_TEMPLATE_REPO_MARKER"] = str(repo_marker)
    env["AGENT_TEMPLATE_MACHINE_MARKER"] = str(machine_marker)
    repo = tmp_path / "standalone-template"
    remote = tmp_path / "remote.git"
    install_root = tmp_path / "install"
    state_root = tmp_path / "state"
    init_repo(repo, env)
    (repo / "Makefile").write_text(
        "repo-check:\n"
        "\t@printf 'repo:%s\\n' \"$(PYTHON)\" >> \"$$AGENT_TEMPLATE_REPO_MARKER\"\n\n"
        "machine-check:\n"
        "\t@printf 'machine:%s\\n' \"$(PYTHON)\" >> \"$$AGENT_TEMPLATE_MACHINE_MARKER\"\n",
        encoding="utf-8",
    )
    git(repo, env, "add", "Makefile")
    git(repo, env, "commit", "-qm", "add repository checks")
    git(repo, env, "init", "--bare", "-q", str(remote))
    git(repo, env, "remote", "add", "origin", str(remote))
    git(repo, env, "config", "core.hooksPath", "legacy-hooks")
    git(repo, env, "config", "agent.runtime.enabled", "true")
    git(repo, env, "config", "agent.runtime.profile", profile)

    installed = dispatcher(
        repo,
        home,
        install_root,
        state_root,
        "install",
        "--registry",
        str(REGISTRY),
    )
    assert installed.stderr == ""
    installed_payload = json.loads(installed.stdout)
    assert installed_payload["previous_hooks_path"] == "legacy-hooks"

    head_before = git(repo, env, "rev-parse", "HEAD").stdout.strip()
    (repo / "sample.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    git(repo, env, "add", "sample.py")
    blocked = git(repo, env, "commit", "-m", "bad syntax", check=False)

    assert blocked.returncode != 0
    assert "template-staged-python-syntax" in blocked.stderr
    assert "SyntaxError" in blocked.stderr or "invalid syntax" in blocked.stderr
    assert git(repo, env, "rev-parse", "HEAD").stdout.strip() == head_before

    (repo / "sample.py").write_text("def working():\n    return 1\n", encoding="utf-8")
    git(repo, env, "add", "sample.py")
    (repo / "sample.py").write_text("def unstaged_broken(:\n    pass\n", encoding="utf-8")
    committed = git(repo, env, "commit", "-m", "repair staged syntax")
    assert committed.stderr == ""
    assert git(repo, env, "show", "HEAD:sample.py").stdout == "def working():\n    return 1\n"
    assert (repo / "sample.py").read_text(encoding="utf-8") == "def unstaged_broken(:\n    pass\n"
    pushed = git(repo, env, "push", "-u", "origin", "main")
    assert "agent-runtime" not in pushed.stderr

    local_sha = git(repo, env, "rev-parse", "HEAD").stdout.strip()
    remote_sha = run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
        cwd=repo,
        env=env,
    ).stdout.strip()
    assert local_sha == remote_sha
    if profile == "mac-bootstrap-template":
        assert repo_marker.read_text(encoding="utf-8").splitlines() == [
            f"repo:{sys.executable}"
        ]
    else:
        assert repo_marker.exists() is False
    assert machine_marker.exists() is False

    doctor = dispatcher(repo, home, install_root, state_root, "doctor")
    doctor_payload = json.loads(doctor.stdout)
    assert doctor_payload["healthy"] is True
    assert doctor_payload["hooks_path_matches"] is True

    removed = dispatcher(repo, home, install_root, state_root, "uninstall")
    assert json.loads(removed.stdout)["restored_hooks_path"] == "legacy-hooks"
    assert git(repo, env, "config", "--get", "core.hooksPath").stdout.strip() == "legacy-hooks"


def test_template_push_gate_rejects_missing_ref_metadata(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    git(repo, env, "config", "agent.runtime.enabled", "true")
    git(repo, env, "config", "agent.runtime.profile", "mac-bootstrap-template")
    event = {
        "schema_version": 1,
        "event_type": "before.push",
        "event_id": "template-push-missing-refs",
        "source_adapter": "test",
        "timestamp": "2026-07-28T00:00:00Z",
        "cwd": str(repo),
        "target_paths": [],
        "session_id": "template-profile-test",
        "metadata": {"refs": []},
    }

    result = run(
        [sys.executable, str(RUNTIME), "--registry", str(REGISTRY), "dispatch"],
        cwd=repo,
        env=env,
        input_text=json.dumps(event),
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "template-push-ref-integrity" in result.stderr
    assert "at least one ref" in result.stderr
