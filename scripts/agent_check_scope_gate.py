#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


MANAGEMENT_CONFIG = "agent.runtime.managementCheckout"
MAKE = "/usr/bin/make"


class CheckScopeError(RuntimeError):
    pass


def _required_path(name: str, *, directory: bool = False) -> Path:
    raw = os.environ.get(name, "")
    if not raw:
        raise CheckScopeError(f"{name} is required")
    path = Path(raw).resolve()
    if directory and not path.is_dir():
        raise CheckScopeError(f"{name} is not a directory: {path}")
    return path


def _management_enabled(policy_config: Path) -> bool:
    result = subprocess.run(
        [
            "git",
            "config",
            "--file",
            str(policy_config),
            "--get",
            "--bool",
            MANAGEMENT_CONFIG,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 1:
        return False
    if result.returncode != 0:
        detail = result.stderr.strip() or "invalid management checkout config"
        raise CheckScopeError(detail)
    value = result.stdout.strip().lower()
    if value not in {"true", "false"}:
        raise CheckScopeError(f"{MANAGEMENT_CONFIG} must be true or false")
    return value == "true"


def _is_primary_checkout() -> bool:
    git_dir = _required_path("AGENT_RUNTIME_GIT_DIR")
    common_dir = _required_path("AGENT_RUNTIME_GIT_COMMON_DIR")
    superproject = os.environ.get("AGENT_RUNTIME_SUPERPROJECT_ROOT", "")
    return git_dir == common_dir and not superproject


def _run_make(repo_root: Path, target: str) -> int:
    result = subprocess.run(
        [MAKE, target],
        cwd=repo_root,
        env=os.environ.copy(),
        check=False,
    )
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in {"repository", "machine"}:
        print("usage: agent_check_scope_gate.py <repository|machine>", file=sys.stderr)
        return 2
    try:
        repo_root = _required_path("AGENT_RUNTIME_REPO_ROOT", directory=True)
        if args[0] == "repository":
            return _run_make(repo_root, "repo-check")
        policy_config = _required_path("AGENT_RUNTIME_POLICY_CONFIG")
        if not _management_enabled(policy_config) or not _is_primary_checkout():
            return 0
        return _run_make(repo_root, "machine-check")
    except CheckScopeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
