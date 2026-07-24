#!/usr/bin/env python3
"""Isolated Githooks transport proof of concept for Template Issue #41.

The script never reads or writes the caller's real global Git configuration.
It expects an already installed Githooks prefix whose HOME contains the
Githooks-managed .gitconfig and binaries.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class CommandError(RuntimeError):
    def __init__(self, command: list[str], result: subprocess.CompletedProcess[str]):
        super().__init__(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        self.command = command
        self.result = result


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise CommandError(command, result)
    return result


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def init_repo(path: Path, env: dict[str, str], *, bare: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    command = ["git", "init", "-q"]
    if bare:
        command.append("--bare")
    command.append(str(path))
    run(command, env=env)
    if not bare:
        run(["git", "config", "user.name", "Githooks PoC"], cwd=path, env=env)
        run(["git", "config", "user.email", "githooks-poc.invalid"], cwd=path, env=env)


def commit_all(repo: Path, env: dict[str, str], message: str) -> subprocess.CompletedProcess[str]:
    run(["git", "add", "-A"], cwd=repo, env=env)
    return run(["git", "commit", "-q", "-m", message], cwd=repo, env=env, check=False)


def git_dir(repo: Path, env: dict[str, str]) -> Path:
    value = run(["git", "rev-parse", "--absolute-git-dir"], cwd=repo, env=env).stdout.strip()
    return Path(value)


def git_path(repo: Path, env: dict[str, str], path: str) -> Path:
    value = run(["git", "rev-parse", "--git-path", path], cwd=repo, env=env).stdout.strip()
    resolved = Path(value)
    if not resolved.is_absolute():
        resolved = (repo / resolved).resolve()
    return resolved


def hook_wrapper(repo: Path, env: dict[str, str], hook_name: str) -> Path:
    configured = run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=repo,
        env=env,
        check=False,
    ).stdout.strip()
    if configured:
        base = Path(configured)
        if not base.is_absolute():
            base = (repo / base).resolve()
        return base / hook_name
    return git_path(repo, env, f"hooks/{hook_name}")


def list_ns_paths(repo: Path, env: dict[str, str]) -> tuple[str, list[str]]:
    result = run(["git", "hooks", "list"], cwd=repo, env=env, check=False)
    combined = f"{result.stdout}\n{result.stderr}"
    paths = sorted(set(re.findall(r"ns:[^\s'\"]+", combined)))
    return combined, paths


def trust_paths(repo: Path, env: dict[str, str], prefixes: tuple[str, ...]) -> list[str]:
    _, paths = list_ns_paths(repo, env)
    selected = [path for path in paths if path.startswith(prefixes)]
    if not selected:
        raise RuntimeError(f"no hook namespace paths matched {prefixes}: {paths}")
    command = ["git", "hooks", "trust", "hooks"]
    for path in selected:
        command.extend(["--path", path])
    run(command, cwd=repo, env=env)
    return selected


def configure_repo(
    repo: Path,
    env: dict[str, str],
    shared_url: str,
    *,
    maintained: bool,
) -> dict[str, Any]:
    install = ["git", "hooks", "install", "--non-interactive"]
    if maintained:
        install.extend(["--maintained-hooks", "pre-commit,pre-push"])
    install_result = run(install, cwd=repo, env=env, check=False)
    if install_result.returncode != 0:
        raise CommandError(install, install_result)

    run(["git", "hooks", "shared", "add", "--local", shared_url], cwd=repo, env=env)
    update_env = dict(env)
    update_env["GITHOOKS_LOG_LEVEL"] = "info"
    update = run(
        ["git", "hooks", "shared", "update"],
        cwd=repo,
        env=update_env,
        check=False,
    )
    if update.returncode != 0:
        raise CommandError(["git", "hooks", "shared", "update"], update)
    run(
        ["git", "hooks", "config", "disable-shared-hooks-update", "--set", "--local"],
        cwd=repo,
        env=env,
    )
    run(
        ["git", "hooks", "config", "non-interactive-runner", "--enable", "--local"],
        cwd=repo,
        env=env,
    )
    run(
        ["git", "hooks", "config", "skip-untrusted-hooks", "--disable", "--local"],
        cwd=repo,
        env=env,
    )
    run(
        ["git", "hooks", "ignore", "add", "--pattern", "ns:gh-self/**"],
        cwd=repo,
        env=env,
    )
    listing, ns_paths = list_ns_paths(repo, env)
    if not any(path.startswith("ns:mac-bootstrap-poc/") for path in ns_paths):
        configured_shared = run(
            ["git", "config", "--local", "--get-all", "githooks.shared"],
            cwd=repo,
            env=env,
            check=False,
        ).stdout.splitlines()
        raise RuntimeError(
            "shared hooks were not discovered\n"
            f"configured={configured_shared}\n"
            f"update stdout={update.stdout}\nupdate stderr={update.stderr}\n"
            f"list={listing}"
        )
    trusted = trust_paths(
        repo,
        env,
        ("ns:mac-bootstrap-poc/", "ns:gh-self-repl/", "ns:gh-replaced/"),
    )
    return {
        "core_hooks_path": run(
            ["git", "config", "--local", "--get", "core.hooksPath"],
            cwd=repo,
            env=env,
            check=False,
        ).stdout.strip(),
        "listing": listing,
        "namespace_paths": ns_paths,
        "trusted_paths": trusted,
        "git_dir": str(git_dir(repo, env)),
    }


def create_shared_hooks(root: Path, env: dict[str, str]) -> tuple[str, Path, str]:
    source = root / "shared-source"
    init_repo(source, env)
    (source / ".namespace").write_text("mac-bootstrap-poc\n", encoding="utf-8")
    hook_template = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

HOOK = {hook_name!r}
entry = {{"hook": HOOK, "argv": sys.argv[1:]}}
if HOOK == "pre-push":
    entry["stdin"] = sys.stdin.read()
log = os.environ.get("POC_LOG")
if log:
    with Path(log).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\\n")
audit = os.environ.get("POC_AUDIT_LOG")
if audit:
    try:
        with Path(audit).open("a", encoding="utf-8") as handle:
            handle.write("audit\\n")
    except OSError as exc:
        print(f"audit write failed: {{exc}}", file=sys.stderr)
        raise SystemExit(41)
raise SystemExit(int(os.environ.get("POC_EXIT_CODE", "0")))
"""
    write_executable(
        source / "pre-commit" / "transport.py",
        hook_template.format(hook_name="pre-commit"),
    )
    write_executable(
        source / "pre-push" / "transport.py",
        hook_template.format(hook_name="pre-push"),
    )
    commit_all(source, env, "test: add trusted shared hooks")
    revision = run(["git", "rev-parse", "HEAD"], cwd=source, env=env).stdout.strip()
    tag = "poc-v1"
    run(["git", "tag", tag], cwd=source, env=env)
    bare = root / "shared.git"
    run(["git", "clone", "-q", "--bare", str(source), str(bare)], env=env)
    return f"{bare.resolve().as_uri()}@{tag}", source, revision


def create_target(root: Path, name: str, env: dict[str, str], *, legacy: bool) -> Path:
    repo = root / name
    init_repo(repo, env)
    (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
    self_marker = root / f"{name}-self.marker"
    write_executable(
        repo / ".githooks" / "pre-commit" / "self.py",
        "#!/usr/bin/env python3\n"
        "import os\n"
        "from pathlib import Path\n"
        "marker = os.environ.get('SELF_MARKER')\n"
        "if marker:\n"
        "    Path(marker).write_text('self hook ran\\n', encoding='utf-8')\n",
    )
    commit_all(repo, env, "test: initialize target")
    if legacy:
        legacy_marker = root / f"{name}-legacy.marker"
        write_executable(
            git_dir(repo, env) / "hooks" / "pre-push",
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            "from pathlib import Path\n"
            "sys.stdin.read()\n"
            "marker = os.environ.get('LEGACY_MARKER')\n"
            "if marker:\n"
            "    Path(marker).write_text('legacy hook ran\\n', encoding='utf-8')\n",
        )
        legacy_marker.unlink(missing_ok=True)
    self_marker.unlink(missing_ok=True)
    return repo


def exercise_transport(
    repo: Path,
    root: Path,
    env: dict[str, str],
    *,
    label: str,
) -> dict[str, Any]:
    log_path = root / f"{label}.jsonl"
    self_marker = root / f"{label}-self.marker"
    legacy_marker = root / f"{label}-legacy.marker"
    remote = root / f"{label}-remote.git"
    init_repo(remote, env, bare=True)
    run(["git", "remote", "add", "origin", str(remote)], cwd=repo, env=env)

    hook_env = dict(env)
    hook_env.update(
        {
            "POC_LOG": str(log_path),
            "SELF_MARKER": str(self_marker),
            "LEGACY_MARKER": str(legacy_marker),
        }
    )

    wrapper = hook_wrapper(repo, env, "pre-push")
    synthetic_stdin = (
        "refs/heads/main deadbeef refs/heads/main "
        "0000000000000000000000000000000000000000\n"
    )
    direct = run(
        [str(wrapper), "origin", str(remote)],
        cwd=repo,
        env=hook_env,
        stdin=synthetic_stdin,
        check=False,
    )
    exit_env = dict(hook_env)
    exit_env["POC_EXIT_CODE"] = "23"
    exit_result = run(
        [str(wrapper), "origin", str(remote)],
        cwd=repo,
        env=exit_env,
        stdin=synthetic_stdin,
        check=False,
    )
    audit_env = dict(hook_env)
    audit_env["POC_AUDIT_LOG"] = str(root)
    audit_result = run(
        [str(wrapper), "origin", str(remote)],
        cwd=repo,
        env=audit_env,
        stdin=synthetic_stdin,
        check=False,
    )

    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    commit_result = commit_all(repo, hook_env, "test: exercise pre-commit")
    push_result = run(
        ["git", "push", "-q", "-u", "origin", "HEAD:main"],
        cwd=repo,
        env=hook_env,
        check=False,
    )

    entries = []
    if log_path.exists():
        entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    return {
        "wrapper": str(wrapper),
        "direct_returncode": direct.returncode,
        "direct_stderr": direct.stderr,
        "exit_23_returncode": exit_result.returncode,
        "exit_23_stderr": exit_result.stderr,
        "audit_unwritable_returncode": audit_result.returncode,
        "audit_unwritable_stderr": audit_result.stderr,
        "commit_returncode": commit_result.returncode,
        "commit_stderr": commit_result.stderr,
        "push_returncode": push_result.returncode,
        "push_stderr": push_result.stderr,
        "self_hook_ran": self_marker.exists(),
        "legacy_hook_ran": legacy_marker.exists(),
        "log_entries": entries,
    }


def exercise_linked_worktree(
    repo: Path,
    root: Path,
    env: dict[str, str],
    *,
    label: str,
) -> dict[str, Any]:
    linked = root / f"{label}-linked"
    run(["git", "worktree", "add", "-q", "-b", f"{label}-linked", str(linked)], cwd=repo, env=env)
    hook_env = dict(env)
    hook_env["POC_LOG"] = str(root / f"{label}-linked.jsonl")
    (linked / "linked.txt").write_text("linked\n", encoding="utf-8")
    run(["git", "add", "linked.txt"], cwd=linked, env=hook_env)
    first_commit = run(
        ["git", "commit", "-q", "-m", "test: linked worktree"],
        cwd=linked,
        env=hook_env,
        check=False,
    )
    listing_before, paths_before = list_ns_paths(linked, env)
    main_git_dir = git_dir(repo, env)
    linked_git_dir = git_dir(linked, env)
    linked_ignore_exists_before_fix = (linked_git_dir / ".githooks.ignore.yaml").exists()
    linked_checksums_exist_before_fix = (linked_git_dir / ".githooks.checksums").exists()
    run(
        ["git", "hooks", "ignore", "add", "--pattern", "ns:gh-self/**"],
        cwd=linked,
        env=env,
    )
    trusted = trust_paths(
        linked,
        env,
        ("ns:mac-bootstrap-poc/", "ns:gh-replaced/", "ns:gh-self-repl/"),
    )
    second_commit = run(
        ["git", "commit", "-q", "-m", "test: linked worktree"],
        cwd=linked,
        env=hook_env,
        check=False,
    )
    listing_after, paths_after = list_ns_paths(linked, env)
    log_path = Path(hook_env["POC_LOG"])
    entries = []
    if log_path.exists():
        entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    return {
        "path": str(linked),
        "git_dir": str(linked_git_dir),
        "main_git_dir": str(main_git_dir),
        "core_hooks_path": run(
            ["git", "config", "--local", "--get", "core.hooksPath"],
            cwd=linked,
            env=env,
            check=False,
        ).stdout.strip(),
        "wrapper": str(hook_wrapper(linked, env, "pre-commit")),
        "wrapper_exists": hook_wrapper(linked, env, "pre-commit").exists(),
        "first_commit_returncode": first_commit.returncode,
        "first_commit_stderr": first_commit.stderr,
        "main_ignore_exists": (main_git_dir / ".githooks.ignore.yaml").exists(),
        "linked_ignore_exists_before_fix": linked_ignore_exists_before_fix,
        "linked_ignore_exists_after_fix": (linked_git_dir / ".githooks.ignore.yaml").exists(),
        "main_checksums_exists": (main_git_dir / ".githooks.checksums").exists(),
        "linked_checksums_exist_before_fix": linked_checksums_exist_before_fix,
        "linked_checksums_exists_after_fix": (linked_git_dir / ".githooks.checksums").exists(),
        "trusted_after_failure": trusted,
        "second_commit_returncode": second_commit.returncode,
        "second_commit_stderr": second_commit.stderr,
        "listing_before_fix": listing_before,
        "namespace_paths_before_fix": paths_before,
        "listing_after_fix": listing_after,
        "namespace_paths_after_fix": paths_after,
        "log_entries": entries,
    }


def exercise_clone_and_submodule(
    source: Path,
    root: Path,
    env: dict[str, str],
    shared_url: str,
) -> dict[str, Any]:
    origin = root / "target-origin.git"
    run(["git", "clone", "-q", "--bare", str(source), str(origin)], env=env)

    clone = root / "independent-clone"
    run(["git", "clone", "-q", str(origin), str(clone)], env=env)
    run(["git", "config", "user.name", "Githooks PoC"], cwd=clone, env=env)
    run(["git", "config", "user.email", "githooks-poc.invalid"], cwd=clone, env=env)
    clone_before = run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=clone,
        env=env,
        check=False,
    ).stdout.strip()
    clone_config = configure_repo(clone, env, shared_url, maintained=False)

    parent = root / "parent"
    init_repo(parent, env)
    (parent / "README.md").write_text("parent\n", encoding="utf-8")
    commit_all(parent, env, "test: initialize parent")
    add = run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(origin), "child"],
        cwd=parent,
        env=env,
        check=False,
    )
    if add.returncode != 0:
        raise CommandError(["git", "submodule", "add"], add)
    commit_all(parent, env, "test: add child submodule")
    parent_before = run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=parent,
        env=env,
        check=False,
    ).stdout.strip()
    parent_config = configure_repo(parent, env, shared_url, maintained=False)

    child = parent / "child"
    run(["git", "config", "user.name", "Githooks PoC"], cwd=child, env=env)
    run(["git", "config", "user.email", "githooks-poc.invalid"], cwd=child, env=env)
    child_before = run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=child,
        env=env,
        check=False,
    ).stdout.strip()
    child_config = configure_repo(child, env, shared_url, maintained=False)

    return {
        "independent_clone": {
            "core_hooks_path_before_opt_in": clone_before,
            "config": clone_config,
            "uninstall": exercise_uninstall(clone, env),
        },
        "parent": {
            "core_hooks_path_before_opt_in": parent_before,
            "config": parent_config,
            "uninstall": exercise_uninstall(parent, env),
        },
        "submodule": {
            "core_hooks_path_before_opt_in": child_before,
            "config": child_config,
            "superproject": run(
                ["git", "rev-parse", "--show-superproject-working-tree"],
                cwd=child,
                env=env,
            ).stdout.strip(),
            "uninstall": exercise_uninstall(child, env),
        },
    }


def exercise_missing_and_changed_trust(
    repo: Path,
    root: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    shared_root_result = run(
        ["git", "hooks", "shared", "root", "ns:mac-bootstrap-poc"],
        cwd=repo,
        env=env,
        check=False,
    )
    shared_root = Path(shared_root_result.stdout.strip())
    wrapper = hook_wrapper(repo, env, "pre-commit")
    hook_env = dict(env)
    hook_env["POC_LOG"] = str(root / "trust-failures.jsonl")

    hook_file = shared_root / "pre-commit" / "transport.py"
    original = hook_file.read_text(encoding="utf-8")
    hook_file.write_text(original + "\n# changed by PoC\n", encoding="utf-8")
    changed = run([str(wrapper)], cwd=repo, env=hook_env, stdin="", check=False)
    hook_file.write_text(original, encoding="utf-8")
    trust_paths(repo, env, ("ns:mac-bootstrap-poc/",))

    missing = shared_root.with_name(shared_root.name + ".missing")
    shared_root.rename(missing)
    try:
        absent = run([str(wrapper)], cwd=repo, env=hook_env, stdin="", check=False)
    finally:
        missing.rename(shared_root)
    trust_paths(repo, env, ("ns:mac-bootstrap-poc/",))

    return {
        "shared_root": str(shared_root),
        "changed_hook_returncode": changed.returncode,
        "changed_hook_stderr": changed.stderr,
        "missing_shared_returncode": absent.returncode,
        "missing_shared_stderr": absent.stderr,
    }


def exercise_uninstall(repo: Path, env: dict[str, str]) -> dict[str, Any]:
    hooks_dir = git_dir(repo, env) / "hooks"
    before = {
        "core_hooks_path": run(
            ["git", "config", "--local", "--get", "core.hooksPath"],
            cwd=repo,
            env=env,
            check=False,
        ).stdout.strip(),
        "shared": run(
            ["git", "config", "--local", "--get-all", "githooks.shared"],
            cwd=repo,
            env=env,
            check=False,
        ).stdout.splitlines(),
        "pre_push_hook_exists": (hooks_dir / "pre-push").exists(),
        "legacy_backup_exists": (hooks_dir / "pre-push.replaced.githook").exists(),
    }
    result = run(["git", "hooks", "uninstall"], cwd=repo, env=env, check=False)
    full_result = run(["git", "hooks", "uninstall", "--full"], cwd=repo, env=env, check=False)
    after = {
        "core_hooks_path": run(
            ["git", "config", "--local", "--get", "core.hooksPath"],
            cwd=repo,
            env=env,
            check=False,
        ).stdout.strip(),
        "shared": run(
            ["git", "config", "--local", "--get-all", "githooks.shared"],
            cwd=repo,
            env=env,
            check=False,
        ).stdout.splitlines(),
        "checksum_dir_exists": (git_dir(repo, env) / ".githooks.checksums").exists(),
        "ignore_file_exists": (git_dir(repo, env) / ".githooks.ignore.yaml").exists(),
        "local_githooks_config": run(
            ["git", "config", "--local", "--get-regexp", "^githooks\\."],
            cwd=repo,
            env=env,
            check=False,
        ).stdout.splitlines(),
        "pre_push_hook_exists": (hooks_dir / "pre-push").exists(),
        "legacy_backup_exists": (hooks_dir / "pre-push.replaced.githook").exists(),
        "pre_push_hook_is_legacy": (
            (hooks_dir / "pre-push").exists()
            and "legacy hook ran"
            in (hooks_dir / "pre-push").read_text(encoding="utf-8")
        ),
    }
    return {
        "before": before,
        "uninstall_returncode": result.returncode,
        "uninstall_stdout": result.stdout,
        "uninstall_stderr": result.stderr,
        "full_uninstall_returncode": full_result.returncode,
        "full_uninstall_stdout": full_result.stdout,
        "full_uninstall_stderr": full_result.stderr,
        "after": after,
    }


def exercise_lfs(root: Path, env: dict[str, str], shared_url: str) -> dict[str, Any]:
    version = run(["git", "lfs", "version"], env=env, check=False)
    if version.returncode != 0:
        return {"available": False, "reason": version.stderr.strip() or version.stdout.strip()}

    repo = root / "lfs"
    init_repo(repo, env)
    (repo / "README.md").write_text("lfs\n", encoding="utf-8")
    commit_all(repo, env, "test: initialize lfs repo")
    run(["git", "lfs", "install", "--local"], cwd=repo, env=env)
    hook = git_dir(repo, env) / "hooks" / "pre-push"
    original = hook.read_text(encoding="utf-8")
    config = configure_repo(repo, env, shared_url, maintained=True)
    replaced = git_dir(repo, env) / "hooks" / "pre-push.disabled.githooks"
    uninstall = run(["git", "hooks", "uninstall"], cwd=repo, env=env, check=False)
    restored = hook.read_text(encoding="utf-8") if hook.exists() else ""
    return {
        "available": True,
        "version": version.stdout.strip(),
        "config": config,
        "disabled_backup_existed": replaced.exists(),
        "uninstall_returncode": uninstall.returncode,
        "restored_matches_original": restored == original,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--githooks-home", type=Path, required=True)
    parser.add_argument("--expected-version", default="3.0.6")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    home = args.githooks_home.resolve()
    cli = home / ".githooks" / "bin" / "githooks-cli"
    runner = home / ".githooks" / "bin" / "githooks-runner"
    if not cli.is_file() or not runner.is_file():
        parser.error(f"invalid isolated Githooks HOME: {home}")

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GITHOOKS_LOG_LEVEL": "error",
        }
    )
    version = run(["git", "hooks", "--version"], env=env).stdout.strip()
    if args.expected_version not in version:
        parser.error(
            f"expected Githooks {args.expected_version}, got: {version or 'unknown'}"
        )
    run(["git", "hooks", "config", "update-check", "--disable"], env=env)

    temp: tempfile.TemporaryDirectory[str] | None = None
    if args.keep:
        root = Path(tempfile.mkdtemp(prefix="githooks-transport-poc-"))
    else:
        temp = tempfile.TemporaryDirectory(prefix="githooks-transport-poc-")
        root = Path(temp.name)
    summary: dict[str, Any] = {
        "githooks_version": version,
        "isolated_home": str(home),
        "work_root": str(root),
        "global_core_hooks_path": run(
            ["git", "config", "--global", "--get", "core.hooksPath"],
            env=env,
            check=False,
        ).stdout.strip(),
    }

    try:
        shared_url, _, revision = create_shared_hooks(root, env)
        summary["shared"] = {"url": shared_url, "revision": revision}

        default_repo = create_target(root, "default", env, legacy=True)
        summary["default_manual"] = {
            "config": configure_repo(default_repo, env, shared_url, maintained=False),
        }
        summary["default_manual"]["transport"] = exercise_transport(
            default_repo, root, env, label="default"
        )
        summary["default_manual"]["linked_worktree"] = exercise_linked_worktree(
            default_repo, root, env, label="default"
        )
        summary["default_manual"]["trust_failures"] = exercise_missing_and_changed_trust(
            default_repo, root, env
        )
        summary["clone_and_submodule"] = exercise_clone_and_submodule(
            default_repo, root, env, shared_url
        )

        maintained_repo = create_target(root, "maintained", env, legacy=True)
        summary["maintained_hooks"] = {
            "config": configure_repo(maintained_repo, env, shared_url, maintained=True),
        }
        summary["maintained_hooks"]["transport"] = exercise_transport(
            maintained_repo, root, env, label="maintained"
        )
        summary["maintained_hooks"]["linked_worktree"] = exercise_linked_worktree(
            maintained_repo, root, env, label="maintained"
        )
        summary["lfs"] = exercise_lfs(root, env, shared_url)

        summary["default_manual"]["uninstall"] = exercise_uninstall(default_repo, env)
        summary["maintained_hooks"]["uninstall"] = exercise_uninstall(maintained_repo, env)
    finally:
        rendered = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        if temp is not None:
            temp.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
