#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence


CONTEXT_SCHEMA_VERSION = 1
DEFAULT_STATE_ROOT = Path(
    "~/.local/state/mac-bootstrap-agent-runtime"
).expanduser()
_GIT_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class GitContextError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        cwd: Path,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = " ".join(message.split())
        self.cwd = cwd.expanduser().resolve(strict=False)
        self.details = dict(details or {})

    @property
    def fingerprint(self) -> str:
        material = json.dumps(
            {
                "schema_version": CONTEXT_SCHEMA_VERSION,
                "code": self.code,
                "cwd": str(self.cwd),
                "details": self.details,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
        return f"ctxerr-{digest}"

    def to_payload(self) -> dict[str, object]:
        return {
            "status": "error",
            "error": {
                "code": self.code,
                "message": self.message,
                "fingerprint": self.fingerprint,
            },
        }


@dataclass(frozen=True)
class RuntimeStatePaths:
    state_root: Path
    repository_dir: Path
    worktree_dir: Path
    session_dir: Path
    ledger_path: Path
    lock_path: Path
    cache_dir: Path
    diagnostics_dir: Path
    accumulator_path: Path
    receipts_dir: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "state_root": str(self.state_root),
            "repository_dir": str(self.repository_dir),
            "worktree_dir": str(self.worktree_dir),
            "session_dir": str(self.session_dir),
            "ledger_path": str(self.ledger_path),
            "lock_path": str(self.lock_path),
            "cache_dir": str(self.cache_dir),
            "diagnostics_dir": str(self.diagnostics_dir),
            "accumulator_path": str(self.accumulator_path),
            "receipts_dir": str(self.receipts_dir),
        }

    def environment(self) -> dict[str, str]:
        return {
            "AGENT_RUNTIME_STATE_ROOT": str(self.state_root),
            "AGENT_RUNTIME_REPOSITORY_STATE_DIR": str(self.repository_dir),
            "AGENT_RUNTIME_WORKTREE_STATE_DIR": str(self.worktree_dir),
            "AGENT_RUNTIME_SESSION_DIR": str(self.session_dir),
            "AGENT_RUNTIME_LEDGER_PATH": str(self.ledger_path),
            "AGENT_RUNTIME_LOCK_PATH": str(self.lock_path),
            "AGENT_RUNTIME_CACHE_DIR": str(self.cache_dir),
            "AGENT_RUNTIME_DIAGNOSTICS_DIR": str(self.diagnostics_dir),
            "AGENT_RUNTIME_ACCUMULATOR_PATH": str(self.accumulator_path),
            "AGENT_RUNTIME_RECEIPTS_DIR": str(self.receipts_dir),
        }


@dataclass(frozen=True)
class GitContext:
    cwd: Path
    repo_root: Path | None
    git_dir: Path
    git_common_dir: Path
    superproject_working_tree: Path | None
    is_bare: bool
    is_inside_work_tree: bool
    is_linked_worktree: bool
    is_submodule: bool
    repository_id: str
    worktree_id: str
    policy_config_path: Path

    @property
    def is_main_checkout(self) -> bool:
        return not self.is_linked_worktree

    def runtime_state_paths(
        self,
        session_id: str,
        state_root: Path = DEFAULT_STATE_ROOT,
    ) -> RuntimeStatePaths:
        if not session_id.strip():
            raise GitContextError(
                "invalid-session-id",
                "session_id must be a non-empty string",
                cwd=self.cwd,
            )
        resolved_root = state_root.expanduser().resolve(strict=False)
        session_slug = _stable_slug(session_id, prefix="session")
        repository_dir = resolved_root / "repositories" / self.repository_id
        worktree_dir = repository_dir / "worktrees" / self.worktree_id
        session_dir = worktree_dir / "sessions" / session_slug
        return RuntimeStatePaths(
            state_root=resolved_root,
            repository_dir=repository_dir,
            worktree_dir=worktree_dir,
            session_dir=session_dir,
            ledger_path=session_dir / "changed-files.jsonl",
            lock_path=session_dir / "runtime.lock",
            cache_dir=session_dir / "cache",
            diagnostics_dir=session_dir / "diagnostics",
            accumulator_path=session_dir / "accumulator.json",
            receipts_dir=session_dir / "receipts",
        )

    def to_dict(
        self,
        *,
        session_id: str | None = None,
        state_root: Path = DEFAULT_STATE_ROOT,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": CONTEXT_SCHEMA_VERSION,
            "repo_root": str(self.repo_root) if self.repo_root else None,
            "git_dir": str(self.git_dir),
            "git_common_dir": str(self.git_common_dir),
            "superproject_working_tree": (
                str(self.superproject_working_tree)
                if self.superproject_working_tree
                else None
            ),
            "is_bare": self.is_bare,
            "is_inside_work_tree": self.is_inside_work_tree,
            "is_linked_worktree": self.is_linked_worktree,
            "is_main_checkout": self.is_main_checkout,
            "is_submodule": self.is_submodule,
            "repository_id": self.repository_id,
            "worktree_id": self.worktree_id,
            "policy_config_path": str(self.policy_config_path),
        }
        if session_id is not None:
            payload["runtime_state"] = self.runtime_state_paths(
                session_id, state_root
            ).to_dict()
        return payload

    def environment(
        self,
        state_paths: RuntimeStatePaths | None = None,
    ) -> dict[str, str]:
        payload = self.to_dict()
        result = {
            "AGENT_RUNTIME_REPO_ROOT": str(self.repo_root or ""),
            "AGENT_RUNTIME_GIT_DIR": str(self.git_dir),
            "AGENT_RUNTIME_GIT_COMMON_DIR": str(self.git_common_dir),
            "AGENT_RUNTIME_SUPERPROJECT_ROOT": str(
                self.superproject_working_tree or ""
            ),
            "AGENT_RUNTIME_REPOSITORY_ID": self.repository_id,
            "AGENT_RUNTIME_WORKTREE_ID": self.worktree_id,
            "AGENT_RUNTIME_POLICY_CONFIG": str(self.policy_config_path),
            "AGENT_RUNTIME_CONTEXT_JSON": json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        if state_paths is not None:
            result.update(state_paths.environment())
        return result


def _stable_identity(prefix: str, path: Path) -> str:
    material = (
        f"agent-runtime-git-context-v{CONTEXT_SCHEMA_VERSION}\0"
        f"{prefix}\0{path.resolve(strict=False)}"
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _stable_slug(value: str, *, prefix: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")[:48]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{normalized or prefix}-{digest}"


def _canonical_directory(cwd: Path) -> Path:
    resolved = cwd.expanduser().resolve(strict=False)
    if not resolved.is_dir():
        raise GitContextError(
            "invalid-cwd",
            f"cwd is not a directory: {resolved}",
            cwd=resolved,
        )
    return resolved


def _raw_git(
    cwd: Path,
    args: Sequence[str],
    *,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
    )


def git_local_environment_names(
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    resolved = _canonical_directory(cwd)
    base_env = dict(os.environ if env is None else env)
    result = _raw_git(resolved, ("rev-parse", "--local-env-vars"), env=base_env)
    if result.returncode != 0:
        detail = result.stderr.strip() or "git rev-parse --local-env-vars failed"
        raise GitContextError(
            "environment-cleanup-failed",
            detail,
            cwd=resolved,
            details={"returncode": result.returncode},
        )
    names = tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
    if not names or any(not _GIT_ENV_NAME.fullmatch(name) for name in names):
        raise GitContextError(
            "environment-cleanup-failed",
            "git returned an invalid local environment variable list",
            cwd=resolved,
        )
    return names


def clean_git_local_environment(
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    base_env = dict(os.environ if env is None else env)
    for name in git_local_environment_names(cwd, base_env):
        base_env.pop(name, None)
    base_env["LC_ALL"] = "C"
    base_env["LANG"] = "C"
    return base_env


def run_in_repository(
    cwd: Path,
    command: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    capture_output: bool = True,
    text: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[Any]:
    resolved = _canonical_directory(cwd)
    if not command:
        raise GitContextError(
            "invalid-command",
            "cross-repository command must not be empty",
            cwd=resolved,
        )
    clean_env = clean_git_local_environment(resolved, env)
    return subprocess.run(
        list(command),
        cwd=resolved,
        env=clean_env,
        check=False,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
    )


def run_git(
    cwd: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return run_in_repository(cwd, ("git", *args), env=env)


def _nearest_git_marker(cwd: Path) -> Path | None:
    for candidate in (cwd, *cwd.parents):
        marker = candidate / ".git"
        if marker.exists() or marker.is_symlink():
            return marker
    return None


def _worktree_metadata_error(cwd: Path) -> tuple[str, str] | None:
    marker = _nearest_git_marker(cwd)
    if marker is None or not marker.is_file():
        return None
    try:
        text = marker.read_text(encoding="utf-8")[:4096].strip()
    except OSError as exc:
        return "broken-worktree", f"cannot read worktree gitfile {marker}: {exc}"
    if not text.lower().startswith("gitdir:"):
        return "broken-worktree", f"invalid worktree gitfile: {marker}"
    raw_target = text.split(":", 1)[1].strip()
    target = Path(raw_target)
    if not target.is_absolute():
        target = (marker.parent / target).resolve(strict=False)
    if not target.is_dir():
        return "broken-worktree", f"worktree git dir is missing: {target}"

    common_file = target / "commondir"
    if common_file.exists():
        try:
            raw_common = common_file.read_text(encoding="utf-8")[:4096].strip()
        except OSError as exc:
            return "missing-common-dir", f"cannot read {common_file}: {exc}"
        if not raw_common:
            return "missing-common-dir", f"worktree commondir is empty: {common_file}"
        common_dir = Path(raw_common)
        if not common_dir.is_absolute():
            common_dir = (target / common_dir).resolve(strict=False)
        if not common_dir.is_dir():
            return "missing-common-dir", f"worktree common dir is missing: {common_dir}"
    return None


def _git_failure(
    cwd: Path,
    result: subprocess.CompletedProcess[str],
    *,
    operation: str,
) -> GitContextError:
    detail = result.stderr.strip() or result.stdout.strip() or f"git {operation} failed"
    lowered = detail.lower()
    if "commondir" in lowered or "common dir" in lowered:
        code = "missing-common-dir"
    else:
        metadata_error = _worktree_metadata_error(cwd)
        if metadata_error:
            code, message = metadata_error
            return GitContextError(
                code,
                message,
                cwd=cwd,
                details={"operation": operation},
            )
        code = "not-a-repository" if operation == "probe" else "git-command-failed"
    return GitContextError(
        code,
        detail,
        cwd=cwd,
        details={"operation": operation, "returncode": result.returncode},
    )


def _path_from_git(
    cwd: Path,
    result: subprocess.CompletedProcess[str],
    *,
    field: str,
    must_exist: bool = True,
) -> Path:
    if result.returncode != 0:
        raise _git_failure(cwd, result, operation=field)
    raw = result.stdout.strip()
    if not raw:
        code = "missing-common-dir" if field == "git-common-dir" else "git-command-failed"
        raise GitContextError(
            code,
            f"git returned an empty {field}",
            cwd=cwd,
            details={"operation": field},
        )
    path = Path(raw)
    if not path.is_absolute():
        path = cwd / path
    resolved = path.resolve(strict=False)
    if must_exist and not resolved.is_dir():
        code = "missing-common-dir" if field == "git-common-dir" else "broken-worktree"
        raise GitContextError(
            code,
            f"resolved {field} is not a directory: {resolved}",
            cwd=cwd,
            details={"operation": field},
        )
    return resolved


def _git_bool(
    cwd: Path,
    result: subprocess.CompletedProcess[str],
    *,
    field: str,
) -> bool:
    if result.returncode != 0:
        raise _git_failure(cwd, result, operation=field)
    value = result.stdout.strip().lower()
    if value not in {"true", "false"}:
        raise GitContextError(
            "git-command-failed",
            f"git returned invalid boolean for {field}: {value!r}",
            cwd=cwd,
            details={"operation": field},
        )
    return value == "true"


def _validate_superproject(
    cwd: Path,
    repo_root: Path,
    superproject: Path,
    *,
    env: Mapping[str, str] | None,
) -> None:
    if superproject == repo_root or not repo_root.is_relative_to(superproject):
        raise GitContextError(
            "inconsistent-superproject",
            "superproject does not contain the repository working tree",
            cwd=cwd,
            details={
                "repo_root": str(repo_root),
                "superproject": str(superproject),
            },
        )
    result = run_git(superproject, "rev-parse", "--show-toplevel", env=env)
    resolved = _path_from_git(
        superproject,
        result,
        field="superproject-toplevel",
    )
    if resolved != superproject:
        raise GitContextError(
            "inconsistent-superproject",
            "reported superproject is not its Git top-level",
            cwd=cwd,
            details={
                "reported": str(superproject),
                "resolved": str(resolved),
            },
        )


def resolve_git_context(
    cwd: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> GitContext:
    resolved_cwd = _canonical_directory(cwd)
    probe = run_git(resolved_cwd, "rev-parse", "--git-dir", env=env)
    if probe.returncode != 0:
        raise _git_failure(resolved_cwd, probe, operation="probe")

    git_dir = _path_from_git(
        resolved_cwd,
        run_git(resolved_cwd, "rev-parse", "--absolute-git-dir", env=env),
        field="git-dir",
    )
    git_common_dir = _path_from_git(
        resolved_cwd,
        run_git(
            resolved_cwd,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
            env=env,
        ),
        field="git-common-dir",
    )
    is_bare = _git_bool(
        resolved_cwd,
        run_git(resolved_cwd, "rev-parse", "--is-bare-repository", env=env),
        field="is-bare-repository",
    )
    is_inside_work_tree = _git_bool(
        resolved_cwd,
        run_git(resolved_cwd, "rev-parse", "--is-inside-work-tree", env=env),
        field="is-inside-work-tree",
    )

    repo_root: Path | None = None
    superproject: Path | None = None
    if not is_bare and is_inside_work_tree:
        repo_root = _path_from_git(
            resolved_cwd,
            run_git(resolved_cwd, "rev-parse", "--show-toplevel", env=env),
            field="repo-root",
        )
        super_result = run_git(
            resolved_cwd,
            "rev-parse",
            "--show-superproject-working-tree",
            env=env,
        )
        if super_result.returncode != 0:
            raise _git_failure(
                resolved_cwd,
                super_result,
                operation="superproject-working-tree",
            )
        if super_result.stdout.strip():
            superproject = _path_from_git(
                resolved_cwd,
                super_result,
                field="superproject-working-tree",
            )
            _validate_superproject(
                resolved_cwd,
                repo_root,
                superproject,
                env=env,
            )

    policy_config_path = git_common_dir / "config"
    if not policy_config_path.is_file():
        raise GitContextError(
            "missing-common-config",
            f"repository common config is missing: {policy_config_path}",
            cwd=resolved_cwd,
            details={"git_common_dir": str(git_common_dir)},
        )

    return GitContext(
        cwd=resolved_cwd,
        repo_root=repo_root,
        git_dir=git_dir,
        git_common_dir=git_common_dir,
        superproject_working_tree=superproject,
        is_bare=is_bare,
        is_inside_work_tree=is_inside_work_tree,
        is_linked_worktree=git_dir != git_common_dir,
        is_submodule=superproject is not None,
        repository_id=_stable_identity("repo", git_common_dir),
        worktree_id=_stable_identity("worktree", git_dir),
        policy_config_path=policy_config_path.resolve(strict=False),
    )


def common_git_config(
    context: GitContext,
    *args: str,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cwd = context.repo_root or context.git_common_dir
    clean_env = clean_git_local_environment(cwd, env)
    return subprocess.run(
        ["git", "config", "--file", str(context.policy_config_path), *args],
        cwd=cwd,
        env=clean_env,
        check=False,
        capture_output=True,
        text=True,
    )


def validate_context_scope(
    context: GitContext,
    *,
    expected_repository_id: str | None = None,
    expected_worktree_id: str | None = None,
) -> None:
    mismatches: dict[str, str] = {}
    if expected_repository_id and context.repository_id != expected_repository_id:
        mismatches["repository_id"] = context.repository_id
    if expected_worktree_id and context.worktree_id != expected_worktree_id:
        mismatches["worktree_id"] = context.worktree_id
    if mismatches:
        raise GitContextError(
            "context-conflict",
            "resolved Git context does not match the expected scope",
            cwd=context.cwd,
            details=mismatches,
        )


def _add_context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--session-id")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--expect-repository-id")
    parser.add_argument("--expect-worktree-id")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-git-context")
    subparsers = parser.add_subparsers(dest="command", required=True)
    resolve_parser = subparsers.add_parser("resolve")
    explain_parser = subparsers.add_parser("explain-context")
    _add_context_arguments(resolve_parser)
    _add_context_arguments(explain_parser)
    return parser


def _emit_error(error: GitContextError) -> None:
    sys.stderr.write(
        json.dumps(
            error.to_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        context = resolve_git_context(args.cwd)
        validate_context_scope(
            context,
            expected_repository_id=args.expect_repository_id,
            expected_worktree_id=args.expect_worktree_id,
        )
        if args.command == "explain-context":
            print(
                json.dumps(
                    context.to_dict(
                        session_id=args.session_id,
                        state_root=args.state_root,
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
            )
        return 0
    except GitContextError as exc:
        _emit_error(exc)
        return 3 if exc.code == "not-a-repository" else 1


if __name__ == "__main__":
    raise SystemExit(main())
