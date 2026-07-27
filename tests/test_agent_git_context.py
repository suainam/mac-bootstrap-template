from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_CLI = ROOT / "scripts" / "agent_git_context.py"
RUNTIME = ROOT / "scripts" / "agent_runtime.py"


def run_git(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def init_repo(repo: Path, *, filename: str = "tracked.txt") -> None:
    repo.mkdir(parents=True)
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.email", "runtime@example.com")
    run_git(repo, "config", "user.name", "Runtime Test")
    (repo / filename).write_text(f"{filename}\n", encoding="utf-8")
    run_git(repo, "add", filename)
    run_git(repo, "commit", "-qm", "initial")


def explain_context(
    cwd: Path,
    *,
    session_id: str | None = None,
    state_root: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(CONTEXT_CLI),
        "explain-context",
        "--cwd",
        str(cwd),
    ]
    if session_id is not None:
        command.extend(["--session-id", session_id])
    if state_root is not None:
        command.extend(["--state-root", str(state_root)])
    runtime_env = os.environ.copy()
    runtime_env.pop("PYTHON", None)
    runtime_env.pop("PYTHON_BIN", None)
    if env:
        runtime_env.update(env)
    return subprocess.run(
        command,
        cwd=cwd,
        env=runtime_env,
        check=False,
        capture_output=True,
        text=True,
    )


def parsed_context(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout)


def write_registry(path: Path, marker: Path, gate_script: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": {
                    "diagnostic_limit": 5,
                    "diagnostic_bytes": 4096,
                    "log_dir": str(path.parent / "runtime-state"),
                },
                "profiles": {"test": {"gates": ["capture"]}},
                "gates": {
                    "capture": {
                        "events": ["after.edit"],
                        "path_globs": ["*.txt"],
                        "command": [sys.executable, str(gate_script), str(marker)],
                        "cwd": "repo",
                        "mode": "sync",
                        "timeout_seconds": 5,
                        "failure_policy": "block",
                        "output_policy": "diagnostic",
                        "capabilities": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def runtime_event(repo: Path, session_id: str = "session-shared") -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_type": "after.edit",
        "event_id": "evt-context",
        "source_adapter": "test",
        "timestamp": "2026-07-27T00:00:00Z",
        "cwd": str(repo),
        "target_paths": ["tracked.txt"],
        "session_id": session_id,
        "metadata": {},
    }


def run_runtime(
    repo: Path,
    registry: Path,
    payload: dict[str, object],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    runtime_env = os.environ.copy()
    runtime_env.pop("PYTHON", None)
    runtime_env.pop("PYTHON_BIN", None)
    if env:
        runtime_env.update(env)
    return subprocess.run(
        [sys.executable, str(RUNTIME), "--registry", str(registry), "dispatch"],
        cwd=repo,
        env=runtime_env,
        input=json.dumps(payload),
        check=False,
        capture_output=True,
        text=True,
    )


def test_context_is_stable_from_subdirectory_and_symlink(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    subdir = repo / "nested" / "directory"
    subdir.mkdir(parents=True)
    symlink = tmp_path / "repo-link"
    symlink.symlink_to(repo, target_is_directory=True)

    from_subdir = parsed_context(explain_context(subdir))
    from_symlink = parsed_context(explain_context(symlink / "nested" / "directory"))

    expected_root = str(repo.resolve())
    expected_git_dir = str((repo / ".git").resolve())
    assert from_subdir == from_symlink
    assert from_subdir["repo_root"] == expected_root
    assert from_subdir["git_dir"] == expected_git_dir
    assert from_subdir["git_common_dir"] == expected_git_dir
    assert from_subdir["policy_config_path"] == str((repo / ".git" / "config").resolve())
    assert from_subdir["is_bare"] is False
    assert from_subdir["is_inside_work_tree"] is True
    assert from_subdir["is_linked_worktree"] is False
    assert from_subdir["is_submodule"] is False


def test_linked_worktrees_share_policy_but_isolate_all_runtime_paths(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    first = tmp_path / "first-worktree"
    second = tmp_path / "second-worktree"
    run_git(repo, "worktree", "add", "-qb", "first", str(first))
    run_git(repo, "worktree", "add", "-qb", "second", str(second))
    run_git(repo, "config", "--local", "agent.runtime.enabled", "true")
    run_git(repo, "config", "--local", "agent.runtime.profile", "test")
    state_root = tmp_path / "state"

    first_context = parsed_context(
        explain_context(first, session_id="same-session", state_root=state_root)
    )
    second_context = parsed_context(
        explain_context(second, session_id="same-session", state_root=state_root)
    )

    assert first_context["repository_id"] == second_context["repository_id"]
    assert first_context["git_common_dir"] == second_context["git_common_dir"]
    assert first_context["policy_config_path"] == second_context["policy_config_path"]
    assert first_context["worktree_id"] != second_context["worktree_id"]
    assert first_context["git_dir"] != second_context["git_dir"]
    assert first_context["is_linked_worktree"] is True
    assert second_context["is_linked_worktree"] is True

    first_paths = first_context["runtime_state"]
    second_paths = second_context["runtime_state"]
    assert isinstance(first_paths, dict)
    assert isinstance(second_paths, dict)
    for key in (
        "session_dir",
        "ledger_path",
        "lock_path",
        "cache_dir",
        "diagnostics_dir",
        "accumulator_path",
        "receipts_dir",
    ):
        assert first_paths[key] != second_paths[key]
        assert str(state_root.resolve()) in str(first_paths[key])
        assert str(state_root.resolve()) in str(second_paths[key])

    marker = tmp_path / "gate-output.json"
    gate_script = tmp_path / "capture.py"
    gate_script.write_text(
        "import json, os, pathlib, subprocess, sys\n"
        "payload = {\n"
        "  'repository_id': os.environ['AGENT_RUNTIME_REPOSITORY_ID'],\n"
        "  'worktree_id': os.environ['AGENT_RUNTIME_WORKTREE_ID'],\n"
        "  'common_dir': os.environ['AGENT_RUNTIME_GIT_COMMON_DIR'],\n"
        "  'ledger': os.environ['AGENT_RUNTIME_LEDGER_PATH'],\n"
        "  'tracked': subprocess.run(['git', 'ls-files'], check=True, capture_output=True, text=True).stdout.splitlines(),\n"
        "}\n"
        "pathlib.Path(sys.argv[1]).write_text(json.dumps(payload))\n",
        encoding="utf-8",
    )
    registry = write_registry(tmp_path / "registry.json", marker, gate_script)

    result = run_runtime(first, registry, runtime_event(first))

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    captured = json.loads(marker.read_text(encoding="utf-8"))
    assert captured["repository_id"] == first_context["repository_id"]
    assert captured["worktree_id"] == first_context["worktree_id"]
    assert captured["common_dir"] == first_context["git_common_dir"]
    assert captured["tracked"] == ["tracked.txt"]
    assert captured["ledger"] != second_paths["ledger_path"]


def test_submodule_and_independent_clone_have_real_distinct_contexts(tmp_path: Path):
    child_source = tmp_path / "child-source"
    init_repo(child_source, filename="child.txt")
    parent = tmp_path / "parent"
    init_repo(parent, filename="parent.txt")
    run_git(
        parent,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(child_source),
        "modules/child",
    )
    run_git(parent, "commit", "-qam", "add child submodule")
    submodule = parent / "modules" / "child"
    clone = tmp_path / "independent-clone"
    run_git(tmp_path, "clone", "-q", str(child_source), str(clone))

    child_context = parsed_context(explain_context(submodule))
    clone_context = parsed_context(explain_context(clone))

    assert child_context["is_submodule"] is True
    assert child_context["superproject_working_tree"] == str(parent.resolve())
    assert child_context["repo_root"] == str(submodule.resolve())
    assert child_context["git_common_dir"] == str(
        (parent / ".git" / "modules" / "modules" / "child").resolve()
    )
    assert clone_context["is_submodule"] is False
    assert clone_context["superproject_working_tree"] is None
    assert child_context["repository_id"] != clone_context["repository_id"]


def test_parent_git_environment_is_removed_before_child_resolution_and_gate(tmp_path: Path):
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    init_repo(parent, filename="parent.txt")
    init_repo(child, filename="tracked.txt")
    run_git(child, "config", "--local", "agent.runtime.enabled", "true")
    run_git(child, "config", "--local", "agent.runtime.profile", "test")

    parent_git_dir = run_git(parent, "rev-parse", "--absolute-git-dir").stdout.strip()
    parent_index = run_git(parent, "rev-parse", "--git-path", "index").stdout.strip()
    contaminated = {
        "GIT_DIR": parent_git_dir,
        "GIT_WORK_TREE": str(parent),
        "GIT_INDEX_FILE": parent_index,
    }

    child_context = parsed_context(explain_context(child, env=contaminated))
    assert child_context["repo_root"] == str(child.resolve())

    marker = tmp_path / "clean-env-output.json"
    gate_script = tmp_path / "capture.py"
    gate_script.write_text(
        "import json, os, pathlib, subprocess, sys\n"
        "payload = {\n"
        "  'tracked': subprocess.run(['git', 'ls-files'], check=True, capture_output=True, text=True).stdout.splitlines(),\n"
        "  'git_dir_env': os.environ.get('GIT_DIR'),\n"
        "  'git_work_tree_env': os.environ.get('GIT_WORK_TREE'),\n"
        "  'git_index_env': os.environ.get('GIT_INDEX_FILE'),\n"
        "}\n"
        "pathlib.Path(sys.argv[1]).write_text(json.dumps(payload))\n",
        encoding="utf-8",
    )
    registry = write_registry(tmp_path / "registry.json", marker, gate_script)

    result = run_runtime(
        child,
        registry,
        runtime_event(child),
        env=contaminated,
    )

    assert result.returncode == 0, result.stderr
    captured = json.loads(marker.read_text(encoding="utf-8"))
    assert captured == {
        "tracked": ["tracked.txt"],
        "git_dir_env": None,
        "git_work_tree_env": None,
        "git_index_env": None,
    }


def test_real_linked_worktree_push_runs_context_hook_and_updates_remote(
    tmp_path: Path,
):
    remote = tmp_path / "remote.git"
    run_git(tmp_path, "init", "--bare", "-q", str(remote))
    repo = tmp_path / "repo"
    init_repo(repo)
    run_git(repo, "remote", "add", "origin", str(remote))
    linked = tmp_path / "push-worktree"
    run_git(repo, "worktree", "add", "-qb", "push-feature", str(linked))

    contaminating_repo = tmp_path / "contaminating-repo"
    init_repo(contaminating_repo, filename="parent.txt")
    contaminating_git_dir = run_git(
        contaminating_repo, "rev-parse", "--absolute-git-dir"
    ).stdout.strip()
    contaminating_index = run_git(
        contaminating_repo, "rev-parse", "--git-path", "index"
    ).stdout.strip()

    marker = tmp_path / "pre-push-context.json"
    state_root = tmp_path / "push-state"
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, subprocess, sys\n"
        f"resolver = {str(CONTEXT_CLI)!r}\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        f"state_root = {str(state_root)!r}\n"
        "env = os.environ.copy()\n"
        f"env['GIT_DIR'] = {contaminating_git_dir!r}\n"
        f"env['GIT_WORK_TREE'] = {str(contaminating_repo)!r}\n"
        f"env['GIT_INDEX_FILE'] = {contaminating_index!r}\n"
        "result = subprocess.run(\n"
        "    [sys.executable, resolver, 'explain-context', '--cwd', os.getcwd(),\n"
        "     '--session-id', 'push-session', '--state-root', state_root],\n"
        "    env=env, check=False, capture_output=True, text=True,\n"
        ")\n"
        "if result.returncode != 0:\n"
        "    sys.stderr.write(result.stderr)\n"
        "    raise SystemExit(result.returncode)\n"
        "payload = json.loads(result.stdout)\n"
        "payload['hook_triggered'] = True\n"
        "payload['quality_gates_bypass'] = os.environ.get('QUALITY_GATES_BYPASS')\n"
        "payload['tracked_files'] = subprocess.run(\n"
        "    ['git', 'ls-files'], check=True, capture_output=True, text=True\n"
        ").stdout.splitlines()\n"
        "marker.write_text(json.dumps(payload), encoding='utf-8')\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)

    push_env = os.environ.copy()
    push_env.pop("QUALITY_GATES_BYPASS", None)
    pushed = subprocess.run(
        ["git", "push", "-u", "origin", "push-feature"],
        cwd=linked,
        env=push_env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert pushed.returncode == 0, pushed.stderr
    evidence = json.loads(marker.read_text(encoding="utf-8"))
    assert evidence["hook_triggered"] is True
    assert evidence["quality_gates_bypass"] is None
    assert evidence["repo_root"] == str(linked.resolve())
    assert evidence["is_linked_worktree"] is True
    assert evidence["tracked_files"] == ["tracked.txt"]
    assert str(state_root.resolve()) in evidence["runtime_state"]["session_dir"]
    remote_head = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/push-feature"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    local_head = run_git(linked, "rev-parse", "HEAD").stdout.strip()
    assert remote_head == local_head


def test_bare_repository_context_is_explicit(tmp_path: Path):
    bare = tmp_path / "bare.git"
    run_git(tmp_path, "init", "--bare", "-q", str(bare))

    context = parsed_context(explain_context(bare))

    assert context["repo_root"] is None
    assert context["git_dir"] == str(bare.resolve())
    assert context["git_common_dir"] == str(bare.resolve())
    assert context["is_bare"] is True
    assert context["is_inside_work_tree"] is False
    assert context["is_linked_worktree"] is False


def test_resolver_silent_mode_scope_conflict_and_runtime_explain(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    explained = parsed_context(explain_context(repo))

    clean_env = os.environ.copy()
    clean_env.pop("PYTHON", None)
    clean_env.pop("PYTHON_BIN", None)
    resolved = subprocess.run(
        [
            sys.executable,
            str(CONTEXT_CLI),
            "resolve",
            "--cwd",
            str(repo),
            "--expect-repository-id",
            str(explained["repository_id"]),
        ],
        cwd=repo,
        env=clean_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert resolved.returncode == 0
    assert resolved.stdout == ""
    assert resolved.stderr == ""

    conflict = subprocess.run(
        [
            sys.executable,
            str(CONTEXT_CLI),
            "resolve",
            "--cwd",
            str(repo),
            "--expect-repository-id",
            "repo-wrong-scope",
        ],
        cwd=repo,
        env=clean_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert conflict.returncode == 1
    conflict_error = json.loads(conflict.stderr)
    assert conflict_error["error"]["code"] == "context-conflict"

    runtime_explain = subprocess.run(
        [
            sys.executable,
            str(RUNTIME),
            "--cwd",
            str(repo),
            "--session-id",
            "runtime-session",
            "explain-context",
        ],
        cwd=repo,
        env=clean_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert runtime_explain.returncode == 0, runtime_explain.stderr
    runtime_context = json.loads(runtime_explain.stdout)
    assert runtime_context["repository_id"] == explained["repository_id"]
    assert runtime_context["runtime_state"]["session_dir"]


def test_missing_common_dir_is_distinct_from_broken_worktree(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    linked = tmp_path / "linked"
    run_git(repo, "worktree", "add", "-qb", "linked", str(linked))
    git_file = linked / ".git"
    git_dir = Path(git_file.read_text(encoding="utf-8").split(":", 1)[1].strip())
    if not git_dir.is_absolute():
        git_dir = (linked / git_dir).resolve()
    (git_dir / "commondir").write_text("../../missing-common\n", encoding="utf-8")

    result = explain_context(linked)

    assert result.returncode == 1
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"]["code"] == "missing-common-dir"
    assert error["error"]["fingerprint"].startswith("ctxerr-")


def test_non_git_and_broken_worktree_errors_are_stable(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()

    first = explain_context(outside)
    second = explain_context(outside)

    assert first.returncode == 3
    assert first.stdout == ""
    assert first.stderr == second.stderr
    outside_error = json.loads(first.stderr)
    assert outside_error["error"]["code"] == "not-a-repository"
    assert outside_error["error"]["fingerprint"].startswith("ctxerr-")

    repo = tmp_path / "repo"
    init_repo(repo)
    linked = tmp_path / "linked"
    run_git(repo, "worktree", "add", "-qb", "linked", str(linked))
    git_file = linked / ".git"
    git_dir = Path(git_file.read_text(encoding="utf-8").split(":", 1)[1].strip())
    if not git_dir.is_absolute():
        git_dir = (linked / git_dir).resolve()
    shutil.rmtree(git_dir)

    broken_first = explain_context(linked)
    broken_second = explain_context(linked)

    assert broken_first.returncode == 1
    assert broken_first.stdout == ""
    assert broken_first.stderr == broken_second.stderr
    broken_error = json.loads(broken_first.stderr)
    assert broken_error["error"]["code"] == "broken-worktree"
    assert broken_error["error"]["fingerprint"].startswith("ctxerr-")
