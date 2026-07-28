from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = ROOT / "scripts" / "agent_git_hook_dispatcher.py"
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
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(env),
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
    git(repo, env, "config", "user.email", "parent-profile@example.com")
    git(repo, env, "config", "user.name", "Parent Profile Test")


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


def test_parent_profile_blocks_unpublished_child_pointer_then_allows_push(
    tmp_path: Path,
):
    home = tmp_path / "home"
    home.mkdir()
    env = clean_env(home)
    child = tmp_path / "child"
    child_remote = tmp_path / "child.git"
    parent = tmp_path / "parent"
    parent_remote = tmp_path / "parent.git"
    install_root = tmp_path / "install"
    state_root = tmp_path / "state"

    init_repo(child, env)
    (child / "child.py").write_text("value = 1\n", encoding="utf-8")
    git(child, env, "add", "child.py")
    git(child, env, "commit", "-qm", "initial child")
    git(child, env, "init", "--bare", "-q", "-b", "main", str(child_remote))
    git(child, env, "remote", "add", "origin", str(child_remote))
    git(child, env, "push", "-u", "origin", "main")

    init_repo(parent, env)
    (parent / "Makefile").write_text(
        "repo-check:\n\t@:\n\nmachine-check:\n\t@:\n",
        encoding="utf-8",
    )
    git(parent, env, "add", "Makefile")
    git(parent, env, "init", "--bare", "-q", "-b", "main", str(parent_remote))
    git(parent, env, "remote", "add", "origin", str(parent_remote))
    git(
        parent,
        env,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(child_remote),
        "template",
    )
    git(parent, env, "commit", "-qam", "initial parent")
    git(parent, env, "push", "-u", "origin", "main")
    git(parent, env, "config", "core.hooksPath", "legacy-hooks")
    git(parent, env, "config", "agent.runtime.enabled", "true")
    git(parent, env, "config", "agent.runtime.profile", "mac-bootstrap-parent")

    installed = dispatcher(
        parent,
        home,
        install_root,
        state_root,
        "install",
        "--registry",
        str(REGISTRY),
    )
    assert installed.stderr == ""
    assert json.loads(installed.stdout)["previous_hooks_path"] == "legacy-hooks"

    checkout = parent / "template"
    git(checkout, env, "config", "user.email", "parent-profile@example.com")
    git(checkout, env, "config", "user.name", "Parent Profile Test")
    (checkout / "child.py").write_text("value = 2\n", encoding="utf-8")
    git(checkout, env, "add", "child.py")
    git(checkout, env, "commit", "-qm", "unpublished child")
    unpublished_oid = git(checkout, env, "rev-parse", "HEAD").stdout.strip()
    git(parent, env, "add", "template")

    blocked = git(parent, env, "commit", "-m", "advance child pointer", check=False)

    assert blocked.returncode != 0
    blocked_payload = json.loads(blocked.stderr)
    diagnostic = blocked_payload["diagnostics"][0]
    assert diagnostic["gate_id"] == "parent-submodule-pointer-reachable"
    assert "not fetchable" in diagnostic["message"]
    assert git(parent, env, "rev-parse", "HEAD:template").stdout.strip() != unpublished_oid

    git(checkout, env, "push", "origin", "HEAD:main")
    gitmodules = parent / ".gitmodules"
    staged_gitmodules = git(parent, env, "show", ":.gitmodules").stdout
    gitmodules.write_text(
        staged_gitmodules.replace(str(child_remote), str(tmp_path / "missing-child.git")),
        encoding="utf-8",
    )
    committed = git(parent, env, "commit", "-m", "advance child pointer")
    assert committed.stderr == ""
    assert git(parent, env, "rev-parse", "HEAD:template").stdout.strip() == unpublished_oid
    assert str(child_remote) in git(parent, env, "show", "HEAD:.gitmodules").stdout
    assert str(tmp_path / "missing-child.git") in gitmodules.read_text(encoding="utf-8")

    pushed = git(parent, env, "push", "origin", "main")
    assert "agent-runtime" not in pushed.stderr
    local_sha = git(parent, env, "rev-parse", "HEAD").stdout.strip()
    remote_sha = run(
        ["git", "--git-dir", str(parent_remote), "rev-parse", "refs/heads/main"],
        cwd=parent,
        env=env,
    ).stdout.strip()
    assert local_sha == remote_sha

    doctor = dispatcher(parent, home, install_root, state_root, "doctor")
    assert json.loads(doctor.stdout)["healthy"] is True

    removed = dispatcher(parent, home, install_root, state_root, "uninstall")
    assert json.loads(removed.stdout)["restored_hooks_path"] == "legacy-hooks"
    assert git(parent, env, "config", "--get", "core.hooksPath").stdout.strip() == "legacy-hooks"


def test_parent_push_splits_repository_and_explicit_management_checks(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = clean_env(home)
    repo_marker = tmp_path / "repo-checks.txt"
    machine_marker = tmp_path / "machine-checks.txt"
    env["AGENT_SCOPE_REPO_MARKER"] = str(repo_marker)
    env["AGENT_SCOPE_MACHINE_MARKER"] = str(machine_marker)
    parent = tmp_path / "parent"
    linked = tmp_path / "linked"
    remote = tmp_path / "parent.git"
    install_root = tmp_path / "install"
    state_root = tmp_path / "state"

    init_repo(parent, env)
    (parent / "Makefile").write_text(
        "repo-check:\n"
        "\t@printf 'repo:%s:%s\\n' \"$$(git branch --show-current)\" \"$$PYTHON\" >> \"$$AGENT_SCOPE_REPO_MARKER\"\n\n"
        "machine-check:\n"
        "\t@printf 'machine:%s:%s\\n' \"$$(git branch --show-current)\" \"$$PYTHON\" >> \"$$AGENT_SCOPE_MACHINE_MARKER\"\n",
        encoding="utf-8",
    )
    (parent / "sample.txt").write_text("initial\n", encoding="utf-8")
    git(parent, env, "add", "Makefile", "sample.txt")
    git(parent, env, "commit", "-qm", "initial parent")
    git(parent, env, "init", "--bare", "-q", "-b", "main", str(remote))
    git(parent, env, "remote", "add", "origin", str(remote))
    git(parent, env, "config", "agent.runtime.enabled", "true")
    git(parent, env, "config", "agent.runtime.profile", "mac-bootstrap-parent")
    dispatcher(
        parent,
        home,
        install_root,
        state_root,
        "install",
        "--registry",
        str(REGISTRY),
    )
    initial_doctor = json.loads(
        dispatcher(parent, home, install_root, state_root, "doctor").stdout
    )
    assert initial_doctor["management_checkout"] is False
    assert initial_doctor["effective_check_scope"] == "repo-only"

    first_push = git(parent, env, "push", "-u", "origin", "main")
    assert first_push.returncode == 0
    assert repo_marker.read_text(encoding="utf-8").splitlines() == [
        f"repo:main:{sys.executable}"
    ]
    assert machine_marker.exists() is False

    git(parent, env, "config", "agent.runtime.managementCheckout", "true")
    management_doctor = json.loads(
        dispatcher(parent, home, install_root, state_root, "doctor").stdout
    )
    assert management_doctor["management_checkout"] is True
    assert management_doctor["effective_check_scope"] == "repo+machine"
    (parent / "sample.txt").write_text("management\n", encoding="utf-8")
    git(parent, env, "add", "sample.txt")
    git(parent, env, "commit", "-qm", "management change")
    git(parent, env, "push", "origin", "main")
    assert repo_marker.read_text(encoding="utf-8").splitlines() == [
        f"repo:main:{sys.executable}",
        f"repo:main:{sys.executable}",
    ]
    assert machine_marker.read_text(encoding="utf-8").splitlines() == [
        f"machine:main:{sys.executable}"
    ]

    git(parent, env, "worktree", "add", "-q", "-b", "linked", str(linked), "main")
    git(linked, env, "config", "user.email", "parent-profile@example.com")
    git(linked, env, "config", "user.name", "Parent Profile Test")
    linked_doctor = json.loads(
        dispatcher(linked, home, install_root, state_root, "doctor").stdout
    )
    assert linked_doctor["management_checkout"] is True
    assert linked_doctor["effective_check_scope"] == "repo-only"
    (linked / "sample.txt").write_text("linked\n", encoding="utf-8")
    git(linked, env, "add", "sample.txt")
    git(linked, env, "commit", "-qm", "linked change")
    git(linked, env, "push", "-u", "origin", "linked")

    assert repo_marker.read_text(encoding="utf-8").splitlines() == [
        f"repo:main:{sys.executable}",
        f"repo:main:{sys.executable}",
        f"repo:linked:{sys.executable}",
    ]
    assert machine_marker.read_text(encoding="utf-8").splitlines() == [
        f"machine:main:{sys.executable}"
    ]
