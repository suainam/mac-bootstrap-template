#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from typing import Any, Mapping, Sequence

from agent_git_context import (
    GitContext,
    GitContextError,
    clean_git_local_environment,
    resolve_git_context,
)


INSTALL_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1
DIAGNOSTIC_LIMIT = 5
DIAGNOSTIC_BYTES = 4096
ZERO_OID = "0" * 40
HOOK_EVENTS: dict[str, tuple[str, bool]] = {
    "pre-commit": ("before.commit", True),
    "commit-msg": ("before.commit-message", True),
    "post-commit": ("after.commit", False),
    "post-checkout": ("after.checkout", False),
    "post-merge": ("after.merge", False),
    "post-rewrite": ("after.rewrite", False),
    "pre-push": ("before.push", True),
}
BUNDLE_FILES = (
    "agent_check_scope_gate.py",
    "agent_git_hook_dispatcher.py",
    "agent_git_context.py",
    "agent_edit_feedback.py",
    "agent_runtime.py",
    "agent_submodule_pointer_gate.py",
)


class HookDispatcherError(RuntimeError):
    pass


def _json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def _sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    clean_env = clean_git_local_environment(cwd, env)
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=clean_env,
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def _git(
    context: GitContext,
    *args: str,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    if context.repo_root is None:
        raise HookDispatcherError("hook dispatcher requires a non-bare worktree")
    return _run(
        ["git", *args],
        cwd=context.repo_root,
        input_bytes=input_bytes,
    )


def _git_text(context: GitContext, *args: str, allow_missing: bool = False) -> str:
    result = _git(context, *args)
    if result.returncode != 0:
        if allow_missing:
            return ""
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise HookDispatcherError(detail or f"git {' '.join(args)} failed")
    return result.stdout.decode("utf-8", errors="surrogateescape").strip()


def _git_config_get(context: GitContext, key: str) -> str | None:
    result = _run(
        ["git", "config", "--file", str(context.policy_config_path), "--get", key],
        cwd=context.repo_root or context.cwd,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise HookDispatcherError(detail or f"cannot read Git config {key}")
    value = result.stdout.decode("utf-8", errors="replace").strip()
    return value or None


def _git_config_set(context: GitContext, key: str, value: str | None) -> None:
    cwd = context.repo_root or context.cwd
    if value is None:
        result = _run(
            [
                "git",
                "config",
                "--file",
                str(context.policy_config_path),
                "--unset-all",
                key,
            ],
            cwd=cwd,
        )
        if result.returncode not in {0, 5}:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise HookDispatcherError(detail or f"cannot unset Git config {key}")
        return
    result = _run(
        [
            "git",
            "config",
            "--file",
            str(context.policy_config_path),
            key,
            value,
        ],
        cwd=cwd,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise HookDispatcherError(detail or f"cannot set Git config {key}")


def _installation_dir(state_root: Path, context: GitContext) -> Path:
    return state_root.expanduser().resolve(strict=False) / "installations" / context.repository_id


def _record_path(state_root: Path, context: GitContext) -> Path:
    return _installation_dir(state_root, context) / "installation.json"


def _load_record(state_root: Path, context: GitContext) -> dict[str, Any]:
    path = _record_path(state_root, context)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HookDispatcherError("trusted hook dispatcher is not installed for this repository") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HookDispatcherError(f"invalid hook installation record: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != INSTALL_SCHEMA_VERSION:
        raise HookDispatcherError("unsupported hook installation record")
    if payload.get("repository_id") != context.repository_id:
        raise HookDispatcherError("hook installation record repository identity mismatch")
    return payload


def _source_directory() -> Path:
    return Path(__file__).resolve().parent


def _default_trusted_python() -> Path:
    candidate = shutil.which("python3") or sys.executable
    return Path(candidate).expanduser().absolute()


def _validate_trusted_python(context: GitContext, path: Path) -> Path:
    requested = path.expanduser()
    if not requested.is_absolute():
        raise HookDispatcherError("trusted Python path must be absolute")
    canonical = requested.resolve(strict=False)
    if not requested.is_file() or not os.access(requested, os.X_OK):
        raise HookDispatcherError(f"trusted Python is not executable: {requested}")
    if _is_repository_controlled_path(context, canonical):
        raise HookDispatcherError(
            f"trusted Python must be outside the repository worktree: {requested}"
        )
    try:
        result = subprocess.run(
            [
                str(requested),
                "-c",
                "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)",
            ],
            cwd=context.repo_root or context.cwd,
            env=clean_git_local_environment(context.repo_root or context.cwd),
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HookDispatcherError(f"cannot validate trusted Python: {exc}") from exc
    if result.returncode != 0:
        raise HookDispatcherError("trusted Python must be version 3.10 or newer")
    return requested


def _bundle_digest(state_root: Path, trusted_python: Path) -> str:
    digest = hashlib.sha256()
    source = _source_directory()
    for name in BUNDLE_FILES:
        path = source / name
        if not path.is_file():
            raise HookDispatcherError(f"bundle source is missing: {path}")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(str(trusted_python).encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(state_root.expanduser().resolve(strict=False)).encode("utf-8"))
    return digest.hexdigest()[:24]


def _hook_script(
    hook_name: str,
    state_root: Path,
    trusted_python: Path,
) -> str:
    python = shlex.quote(str(trusted_python))
    state = shlex.quote(str(state_root.expanduser().resolve(strict=False)))
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"\n'
        f"exec {python} \"$HOOK_DIR/../lib/agent_git_hook_dispatcher.py\" "
        f"--repo \"$PWD\" --state-root {state} dispatch {shlex.quote(hook_name)} \"$@\"\n"
    )


def _bundle_metadata(
    state_root: Path,
    trusted_python: Path,
) -> dict[str, object]:
    return {
        "schema_version": INSTALL_SCHEMA_VERSION,
        "state_root": str(state_root.expanduser().resolve(strict=False)),
        "python": str(trusted_python),
    }


def _read_bundle_metadata(path: Path) -> dict[str, Any]:
    metadata_path = path / "bundle.json"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HookDispatcherError(f"invalid trusted bundle metadata: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != INSTALL_SCHEMA_VERSION:
        raise HookDispatcherError("unsupported trusted bundle metadata")
    return payload


def _prepare_release(
    install_root: Path,
    state_root: Path,
    trusted_python: Path,
) -> tuple[Path, Path | None]:
    install_root = install_root.expanduser().resolve(strict=False)
    resolved_state_root = state_root.expanduser().resolve(strict=False)
    current = install_root / "current"
    previous_target: Path | None = None
    if current.is_symlink():
        previous_target = Path(os.readlink(current))
        if not previous_target.is_absolute():
            previous_target = (current.parent / previous_target).resolve(strict=False)
        current_metadata = _read_bundle_metadata(previous_target)
        if current_metadata.get("state_root") != str(resolved_state_root):
            raise HookDispatcherError(
                "install_root is already bound to a different trusted state_root"
            )
    elif current.exists():
        raise HookDispatcherError("trusted bundle current path is not a symlink")

    releases = install_root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    release = releases / _bundle_digest(resolved_state_root, trusted_python)
    if not release.exists():
        temporary = releases / f".{release.name}.tmp-{uuid.uuid4().hex}"
        try:
            lib = temporary / "lib"
            hooks = temporary / "hooks"
            lib.mkdir(parents=True)
            hooks.mkdir(parents=True)
            for name in BUNDLE_FILES:
                shutil.copy2(_source_directory() / name, lib / name)
            for hook_name in HOOK_EVENTS:
                path = hooks / hook_name
                path.write_text(
                    _hook_script(
                        hook_name,
                        resolved_state_root,
                        trusted_python,
                    ),
                    encoding="utf-8",
                )
                path.chmod(0o700)
            _atomic_write_json(
                temporary / "bundle.json",
                _bundle_metadata(resolved_state_root, trusted_python),
            )
            temporary.chmod(0o700)
            os.replace(temporary, release)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    release_metadata = _read_bundle_metadata(release)
    if release_metadata.get("state_root") != str(resolved_state_root):
        raise HookDispatcherError("trusted release state_root does not match install request")
    if release_metadata.get("python") != str(trusted_python):
        raise HookDispatcherError("trusted release Python does not match install request")
    replacement = install_root / f".current-{uuid.uuid4().hex}"
    replacement.symlink_to(release, target_is_directory=True)
    os.replace(replacement, current)
    return release, previous_target


def _restore_current(install_root: Path, previous_target: Path | None) -> None:
    current = install_root.expanduser().resolve(strict=False) / "current"
    if previous_target is None:
        current.unlink(missing_ok=True)
        return
    replacement = current.parent / f".current-rollback-{uuid.uuid4().hex}"
    replacement.symlink_to(previous_target, target_is_directory=True)
    os.replace(replacement, current)


def _classify_hook(context: GitContext, path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:32768]
    except OSError:
        text = ""
    if "git lfs" in text or "git-lfs" in text:
        return "git-lfs"
    if _is_repository_controlled_path(context, path):
        return "repository-self-hook"
    return "legacy-hook"


def _resolved_hooks_dir(context: GitContext) -> Path:
    value = _git_text(context, "rev-parse", "--path-format=absolute", "--git-path", "hooks")
    return Path(value).resolve(strict=False)


def inventory(context: GitContext, state_root: Path) -> dict[str, object]:
    hooks_dir = _resolved_hooks_dir(context)
    approved_sources: set[str] = set()
    record_path = _record_path(state_root, context)
    if record_path.is_file():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            for entries in (record.get("approved_hooks") or {}).values():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict) and isinstance(entry.get("source_path"), str):
                            approved_sources.add(entry["source_path"])
        except (OSError, json.JSONDecodeError):
            pass
    hooks: list[dict[str, object]] = []
    for event in HOOK_EVENTS:
        path = hooks_dir / event
        if not path.is_file():
            continue
        resolved = path.resolve(strict=False)
        hooks.append(
            {
                "event": event,
                "path": str(resolved),
                "sha256": _sha256_file(resolved),
                "executable": os.access(resolved, os.X_OK),
                "classification": _classify_hook(context, resolved),
                "approved": str(resolved) in approved_sources,
            }
        )
    return {
        "schema_version": INSTALL_SCHEMA_VERSION,
        "repository_id": context.repository_id,
        "hooks_path_config": _git_config_get(context, "core.hooksPath"),
        "resolved_hooks_dir": str(hooks_dir),
        "hooks": hooks,
    }


def _parse_approved_specs(specs: Sequence[str]) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    for spec in specs:
        event, separator, raw_path = spec.partition("=")
        if not separator or event not in HOOK_EVENTS or not raw_path:
            raise HookDispatcherError(
                "--approve-hook must use a known hook name and absolute path: EVENT=/path"
            )
        path = Path(raw_path).expanduser().resolve(strict=False)
        result.append((event, path))
    return result


def _is_repository_controlled_path(context: GitContext, path: Path) -> bool:
    if context.repo_root is None:
        return False
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(context.repo_root):
        return False
    if resolved.is_relative_to(context.git_dir) or resolved.is_relative_to(
        context.git_common_dir
    ):
        return False
    return True


def _validate_registry(path: Path, context: GitContext) -> None:
    from agent_runtime import load_registry

    registry = load_registry(path)
    for gate in registry.gates.values():
        for argument in gate.command:
            candidate = Path(argument).expanduser()
            if candidate.is_absolute() and _is_repository_controlled_path(
                context, candidate
            ):
                raise HookDispatcherError(
                    f"trusted gate {gate.gate_id} references repository-controlled path: {candidate}"
                )


def _maybe_test_install_failure(point: str) -> None:
    if (
        os.environ.get("AGENT_RUNTIME_TESTING") == "1"
        and os.environ.get("AGENT_RUNTIME_INSTALL_FAIL_AT") == point
    ):
        raise HookDispatcherError(f"simulated install failure at {point}")


def install(
    context: GitContext,
    *,
    registry: Path,
    install_root: Path,
    state_root: Path,
    trusted_python: Path,
    approved_specs: Sequence[str],
) -> dict[str, object]:
    if context.repo_root is None:
        raise HookDispatcherError("cannot install hooks for a bare repository")
    registry = registry.expanduser().resolve(strict=False)
    if not registry.is_file():
        raise HookDispatcherError(f"registry does not exist: {registry}")
    _validate_registry(registry, context)
    trusted_python = _validate_trusted_python(context, trusted_python)
    approved = _parse_approved_specs(approved_specs)
    for _, source in approved:
        if not source.is_file() or not os.access(source, os.X_OK):
            raise HookDispatcherError(f"approved hook is not executable: {source}")
        if _is_repository_controlled_path(context, source):
            raise HookDispatcherError(f"repository self hook cannot be approved: {source}")

    installation_dir = _installation_dir(state_root, context)
    configured_before = _git_config_get(context, "core.hooksPath")
    existing_record: dict[str, Any] | None = None
    if (installation_dir / "installation.json").is_file():
        existing_record = _load_record(state_root, context)
    previous_hooks_path = (
        existing_record.get("previous_hooks_path")
        if existing_record is not None
        else _git_config_get(context, "core.hooksPath")
    )
    if previous_hooks_path is not None and not isinstance(previous_hooks_path, str):
        raise HookDispatcherError("invalid previous hooksPath in installation record")

    release, previous_current = _prepare_release(
        install_root,
        state_root,
        trusted_python,
    )
    hooks_path = (install_root.expanduser().resolve(strict=False) / "current" / "hooks")
    transaction = installation_dir.parent / f".{context.repository_id}.tmp-{uuid.uuid4().hex}"
    backup = installation_dir.parent / f".{context.repository_id}.backup-{uuid.uuid4().hex}"
    moved_existing = False
    installed_transaction = False
    try:
        _maybe_test_install_failure("before-state-transaction")
        transaction.mkdir(parents=True, mode=0o700)
        trusted_registry = transaction / "registry.jsonc"
        shutil.copy2(registry, trusted_registry)
        trusted_registry.chmod(0o600)
        approved_payload: dict[str, list[dict[str, object]]] = {}
        for order, (event, source) in enumerate(approved):
            target_dir = transaction / "approved" / event
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{order:03d}-{source.name}"
            shutil.copy2(source, target)
            target.chmod(0o700)
            approved_payload.setdefault(event, []).append(
                {
                    "source_path": str(source),
                    "trusted_path": str(
                        installation_dir / "approved" / event / target.name
                    ),
                    "sha256": _sha256_file(target),
                    "order": order,
                    "classification": _classify_hook(context, source),
                }
            )
        audit_path = installation_dir / "bypass-audit.jsonl"
        record = {
            "schema_version": INSTALL_SCHEMA_VERSION,
            "repository_id": context.repository_id,
            "git_common_dir": str(context.git_common_dir),
            "hooks_path": str(hooks_path),
            "previous_hooks_path": previous_hooks_path,
            "install_root": str(install_root.expanduser().resolve(strict=False)),
            "state_root": str(state_root.expanduser().resolve(strict=False)),
            "trusted_python": str(trusted_python),
            "release": str(release),
            "registry_path": str(installation_dir / "registry.jsonc"),
            "approved_hooks": approved_payload,
            "bypass_audit_path": str(audit_path),
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_write_json(transaction / "installation.json", record)
        if installation_dir.exists():
            os.replace(installation_dir, backup)
            moved_existing = True
        os.replace(transaction, installation_dir)
        installed_transaction = True
        _maybe_test_install_failure("after-state-swap")
        _git_config_set(context, "core.hooksPath", str(hooks_path))
        shutil.rmtree(backup, ignore_errors=True)
        return {
            "status": "installed",
            "repository_id": context.repository_id,
            "hooks_path": str(hooks_path),
            "installation_record": str(installation_dir / "installation.json"),
            "approved_hook_count": sum(len(items) for items in approved_payload.values()),
            "previous_hooks_path": previous_hooks_path,
        }
    except BaseException:
        shutil.rmtree(transaction, ignore_errors=True)
        if installed_transaction and installation_dir.exists():
            shutil.rmtree(installation_dir, ignore_errors=True)
        if moved_existing and backup.exists():
            os.replace(backup, installation_dir)
        try:
            _git_config_set(context, "core.hooksPath", configured_before)
        except HookDispatcherError:
            pass
        _restore_current(install_root, previous_current)
        raise


def uninstall(context: GitContext, *, state_root: Path) -> dict[str, object]:
    record = _load_record(state_root, context)
    current = _git_config_get(context, "core.hooksPath")
    expected = record.get("hooks_path")
    if current != expected:
        raise HookDispatcherError(
            "core.hooksPath no longer matches the trusted dispatcher; refusing rollback"
        )
    previous = record.get("previous_hooks_path")
    if previous is not None and not isinstance(previous, str):
        raise HookDispatcherError("invalid previous hooksPath in installation record")
    _git_config_set(context, "core.hooksPath", previous)
    installation_dir = _installation_dir(state_root, context)
    try:
        shutil.rmtree(installation_dir)
    except OSError as exc:
        try:
            _git_config_set(context, "core.hooksPath", str(expected))
        except HookDispatcherError:
            pass
        raise HookDispatcherError(f"cannot remove hook trust state: {exc}") from exc
    return {
        "status": "uninstalled",
        "repository_id": context.repository_id,
        "restored_hooks_path": previous,
    }


def _event_state_dir(record: Mapping[str, Any], context: GitContext, event_id: str) -> Path:
    state_root = Path(str(record["state_root"]))
    path = (
        state_root
        / "events"
        / context.repository_id
        / context.worktree_id
        / event_id
    )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _nul_paths(result: subprocess.CompletedProcess[bytes]) -> tuple[str, ...]:
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise HookDispatcherError(detail or "git path query failed")
    return tuple(
        chunk.decode("utf-8", errors="surrogateescape")
        for chunk in result.stdout.split(b"\0")
        if chunk
    )


def _staged_paths(context: GitContext) -> tuple[str, ...]:
    return _nul_paths(_git(context, "diff", "--cached", "--name-only", "-z"))


def _worktree_fingerprint(context: GitContext) -> str:
    result = _git(context, "status", "--porcelain=v2", "-z", "--untracked-files=all")
    if result.returncode != 0:
        raise HookDispatcherError("cannot capture worktree state")
    return _sha256_bytes(result.stdout)


def _index_tree(context: GitContext) -> str:
    return _git_text(context, "write-tree")


def _materialize_staged_snapshot(
    context: GitContext,
    event_dir: Path,
    paths: Sequence[str],
) -> tuple[Path, list[dict[str, object]]]:
    snapshot = event_dir / "staged"
    snapshot.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    for relative in paths:
        index = _git(context, "ls-files", "-s", "--", relative)
        raw_index = index.stdout.decode("utf-8", errors="replace").strip()
        entry: dict[str, object] = {"path": relative, "present_in_index": False}
        if index.returncode == 0 and raw_index:
            first = raw_index.splitlines()[0].split(maxsplit=3)
            if len(first) >= 3:
                entry.update(
                    {
                        "mode": first[0],
                        "blob_oid": first[1],
                        "stage": first[2],
                        "present_in_index": True,
                    }
                )
            blob = _git(context, "show", f":{relative}")
            if blob.returncode == 0:
                target = snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob.stdout)
                target.chmod(0o600)
                entry["snapshot_path"] = str(target)
        entries.append(entry)
    return snapshot, entries


def _empty_tree(context: GitContext) -> str:
    result = _git(context, "hash-object", "-t", "tree", "--stdin", input_bytes=b"")
    if result.returncode != 0:
        raise HookDispatcherError("cannot resolve empty tree object")
    return result.stdout.decode().strip()


def _diff_paths(context: GitContext, old: str, new: str) -> tuple[str, ...]:
    return _nul_paths(_git(context, "diff", "--name-only", "-z", old, new))


def _commit_paths(context: GitContext) -> tuple[str, ...]:
    parent = _git(context, "rev-parse", "HEAD^")
    old = (
        parent.stdout.decode().strip()
        if parent.returncode == 0
        else _empty_tree(context)
    )
    return _diff_paths(context, old, "HEAD")


def _parse_push_stdin(
    context: GitContext,
    stdin_bytes: bytes,
) -> tuple[list[dict[str, object]], tuple[str, ...]]:
    refs: list[dict[str, object]] = []
    changed: set[str] = set()
    empty = _empty_tree(context)
    for raw_line in stdin_bytes.decode("utf-8", errors="strict").splitlines():
        if not raw_line.strip():
            continue
        fields = raw_line.split()
        if len(fields) != 4:
            raise HookDispatcherError("invalid pre-push stdin record")
        local_ref, local_oid, remote_ref, remote_oid = fields
        local_zero = local_oid == ZERO_OID
        remote_zero = remote_oid == ZERO_OID
        old = empty if remote_zero else remote_oid
        new = empty if local_zero else local_oid
        changed.update(_diff_paths(context, old, new))
        force_update = False
        if not local_zero and not remote_zero:
            ancestry = _git(context, "merge-base", "--is-ancestor", remote_oid, local_oid)
            if ancestry.returncode not in {0, 1}:
                raise HookDispatcherError("cannot classify pushed ref ancestry")
            force_update = ancestry.returncode == 1
        refs.append(
            {
                "local_ref": local_ref,
                "local_oid": local_oid,
                "remote_ref": remote_ref,
                "remote_oid": remote_oid,
                "force_update": force_update,
            }
        )
    return refs, tuple(sorted(changed))


def _event_payload(
    hook_name: str,
    hook_args: Sequence[str],
    stdin_bytes: bytes,
    context: GitContext,
    record: Mapping[str, Any],
) -> tuple[dict[str, object], Path, str, str | None]:
    event_type, _ = HOOK_EVENTS[hook_name]
    event_id = f"git-{hook_name}-{uuid.uuid4().hex}"
    session_id = os.environ.get("AGENT_RUNTIME_SESSION_ID") or event_id
    event_dir = _event_state_dir(record, context, event_id)
    target_paths: tuple[str, ...] = ()
    metadata: dict[str, object] = {
        "hook_name": hook_name,
        "hook_args": list(hook_args),
    }
    index_before: str | None = None
    worktree_before: str | None = None

    if hook_name in {"pre-commit", "commit-msg"}:
        target_paths = _staged_paths(context)
        index_before = _index_tree(context)
        worktree_before = _worktree_fingerprint(context)
        snapshot, entries = _materialize_staged_snapshot(context, event_dir, target_paths)
        metadata.update(
            {
                "staged_snapshot_dir": str(snapshot),
                "staged_tree": index_before,
                "staged_entries": entries,
            }
        )
        if hook_name == "commit-msg" and hook_args:
            metadata["commit_message_path"] = str(
                (context.repo_root / hook_args[0]).resolve(strict=False)
                if context.repo_root and not Path(hook_args[0]).is_absolute()
                else Path(hook_args[0]).resolve(strict=False)
            )
    elif hook_name == "post-commit":
        target_paths = _commit_paths(context)
        metadata["commit_oid"] = _git_text(context, "rev-parse", "HEAD")
    elif hook_name == "post-checkout":
        if len(hook_args) == 3:
            empty = _empty_tree(context)
            old = empty if hook_args[0] == ZERO_OID else hook_args[0]
            new = empty if hook_args[1] == ZERO_OID else hook_args[1]
            target_paths = _diff_paths(context, old, new)
    elif hook_name == "post-merge":
        old = _git_text(context, "rev-parse", "ORIG_HEAD", allow_missing=True)
        if old:
            target_paths = _diff_paths(context, old, "HEAD")
    elif hook_name == "post-rewrite":
        cache = event_dir / "rewrite-stdin.txt"
        cache.write_bytes(stdin_bytes)
        cache.chmod(0o600)
        metadata["rewrite_stdin_path"] = str(cache)
        changed: set[str] = set()
        rewrites: list[dict[str, str]] = []
        for line in stdin_bytes.decode("utf-8", errors="strict").splitlines():
            fields = line.split()
            if len(fields) >= 2:
                old, new = fields[:2]
                rewrites.append({"old_oid": old, "new_oid": new})
                changed.update(_diff_paths(context, old, new))
        metadata["rewrites"] = rewrites
        target_paths = tuple(sorted(changed))
    elif hook_name == "pre-push":
        cache = event_dir / "pre-push-stdin.txt"
        cache.write_bytes(stdin_bytes)
        cache.chmod(0o600)
        refs, target_paths = _parse_push_stdin(context, stdin_bytes)
        metadata.update(
            {
                "remote_name": hook_args[0] if len(hook_args) > 0 else "",
                "remote_url": hook_args[1] if len(hook_args) > 1 else "",
                "push_stdin_path": str(cache),
                "refs": refs,
            }
        )

    payload = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_type": event_type,
        "event_id": event_id,
        "source_adapter": "git-hook-dispatcher",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cwd": str(context.repo_root or context.cwd),
        "target_paths": list(target_paths),
        "session_id": session_id,
        "metadata": metadata,
    }
    return payload, event_dir, index_before or "", worktree_before


def _profile(context: GitContext) -> tuple[bool, str | None]:
    enabled = (_git_config_get(context, "agent.runtime.enabled") or "").lower() == "true"
    profile = _git_config_get(context, "agent.runtime.profile")
    return enabled, profile


def _append_bypass_audit(
    path: Path,
    *,
    payload: Mapping[str, object],
    context: GitContext,
    profile: str | None,
    reason: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": payload["event_type"],
        "event_id": payload["event_id"],
        "repository_id": context.repository_id,
        "worktree_id": context.worktree_id,
        "profile": profile,
        "target_paths": payload["target_paths"],
        "refs": (payload.get("metadata") or {}).get("refs", []),
        "reason": reason,
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        data = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _diagnostic(
    *,
    source: str,
    exit_code: int,
    message: str,
    log_ref: Path | None,
) -> dict[str, object]:
    normalized = " ".join(message.split())[:1024]
    material = json.dumps(
        {"source": source, "exit_code": exit_code, "message": normalized},
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "source": source,
        "exit_code": exit_code,
        "severity": "error",
        "action": "fix",
        "message": normalized,
        "log_ref": str(log_ref) if log_ref else None,
        "fingerprint": f"hookdiag-{hashlib.sha256(material.encode()).hexdigest()[:24]}",
    }


def _write_failure_log(
    event_dir: Path,
    name: str,
    *,
    stdout: bytes,
    stderr: bytes,
    returncode: int,
) -> Path:
    logs = event_dir / "diagnostics"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"{name}.log"
    content = (
        f"returncode={returncode}\n--- stdout ---\n".encode()
        + stdout
        + b"\n--- stderr ---\n"
        + stderr
        + b"\n"
    )
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def _runtime_result(
    payload: Mapping[str, object],
    context: GitContext,
    record: Mapping[str, Any],
    event_dir: Path,
) -> tuple[int, list[dict[str, object]]]:
    current = Path(str(record["install_root"])) / "current"
    runtime = current / "lib" / "agent_runtime.py"
    registry = Path(str(record["registry_path"]))
    if not runtime.is_file() or not registry.is_file():
        return 1, [
            _diagnostic(
                source="runtime",
                exit_code=1,
                message="trusted runtime or registry is unavailable",
                log_ref=None,
            )
        ]
    trusted_python = Path(str(record.get("trusted_python") or ""))
    if (
        not trusted_python.is_absolute()
        or not trusted_python.is_file()
        or not os.access(trusted_python, os.X_OK)
    ):
        return 1, [
            _diagnostic(
                source="runtime",
                exit_code=1,
                message="trusted Python from installation record is unavailable",
                log_ref=None,
            )
        ]
    result = _run(
        [
            str(trusted_python),
            str(runtime),
            "--registry",
            str(registry),
            "--trusted-python",
            str(trusted_python),
            "dispatch",
        ],
        cwd=context.repo_root or context.cwd,
        input_bytes=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    diagnostics: list[dict[str, object]] = []
    if result.returncode != 0 or result.stdout or result.stderr:
        parsed = False
        if result.stderr:
            try:
                raw = json.loads(result.stderr.decode("utf-8"))
                items = raw.get("diagnostics") if isinstance(raw, dict) else None
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            diagnostics.append({"source": "runtime", **item})
                    parsed = True
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        if not parsed and (result.returncode != 0 or result.stdout or result.stderr):
            log = _write_failure_log(
                event_dir,
                "runtime",
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
            detail = result.stderr.decode("utf-8", errors="replace") or result.stdout.decode(
                "utf-8", errors="replace"
            )
            diagnostics.append(
                _diagnostic(
                    source="runtime",
                    exit_code=result.returncode or 1,
                    message=detail or "runtime produced unexpected output",
                    log_ref=log,
                )
            )
    return result.returncode, diagnostics


def _approved_results(
    hook_name: str,
    hook_args: Sequence[str],
    stdin_bytes: bytes,
    context: GitContext,
    record: Mapping[str, Any],
    event_dir: Path,
) -> tuple[list[int], list[dict[str, object]]]:
    entries = (record.get("approved_hooks") or {}).get(hook_name, [])
    if not isinstance(entries, list):
        raise HookDispatcherError("invalid approved hook list")
    returncodes: list[int] = []
    diagnostics: list[dict[str, object]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise HookDispatcherError("invalid approved hook record")
        path = Path(str(entry.get("trusted_path") or ""))
        expected = entry.get("sha256")
        if not path.is_file() or not os.access(path, os.X_OK) or _sha256_file(path) != expected:
            returncodes.append(1)
            diagnostics.append(
                _diagnostic(
                    source=f"approved-hook:{path.name}",
                    exit_code=1,
                    message="approved hook is missing, not executable, or digest-mismatched",
                    log_ref=None,
                )
            )
            continue
        result = _run(
            [str(path), *hook_args],
            cwd=context.repo_root or context.cwd,
            input_bytes=stdin_bytes,
        )
        returncodes.append(result.returncode)
        if result.returncode != 0:
            log = _write_failure_log(
                event_dir,
                f"approved-{index:03d}-{path.name}",
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
            detail = result.stderr.decode("utf-8", errors="replace") or result.stdout.decode(
                "utf-8", errors="replace"
            )
            diagnostics.append(
                _diagnostic(
                    source=f"approved-hook:{path.name}",
                    exit_code=result.returncode,
                    message=detail or "approved hook failed",
                    log_ref=log,
                )
            )
    return returncodes, diagnostics


def _emit_diagnostics(
    diagnostics: Sequence[Mapping[str, object]],
    *,
    status: str,
) -> None:
    payload: dict[str, object] = {
        "status": status,
        "diagnostics": [dict(item) for item in diagnostics[:DIAGNOSTIC_LIMIT]],
    }
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(rendered.encode("utf-8")) > DIAGNOSTIC_BYTES:
        compact: list[dict[str, object]] = []
        for item in diagnostics[:DIAGNOSTIC_LIMIT]:
            candidate = dict(item)
            candidate["message"] = str(candidate.get("message") or "")[:160]
            compact.append(candidate)
        payload["diagnostics"] = compact
        rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(rendered.encode("utf-8")) > DIAGNOSTIC_BYTES:
        payload = {
            "status": status,
            "diagnostics": [
                {
                    "source": "dispatcher",
                    "exit_code": 1,
                    "message": "diagnostic output truncated; inspect external logs",
                }
            ],
        }
        rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    sys.stderr.write(rendered)


def _dispatch_prepared_event(
    context: GitContext,
    *,
    record: Mapping[str, Any],
    hook_name: str,
    hook_args: Sequence[str],
    stdin_bytes: bytes,
    payload: Mapping[str, object],
    event_dir: Path,
    index_before: str,
    worktree_before: str | None,
) -> int:
    event_type, blocking = HOOK_EVENTS[hook_name]
    enabled, profile = _profile(context)

    if blocking and os.environ.get("QUALITY_GATES_BYPASS") == "1":
        reason = os.environ.get("QUALITY_GATES_BYPASS_REASON", "").strip()
        if not reason:
            raise HookDispatcherError(
                "QUALITY_GATES_BYPASS_REASON is required when QUALITY_GATES_BYPASS=1"
            )
        try:
            _append_bypass_audit(
                Path(str(record["bypass_audit_path"])),
                payload=payload,
                context=context,
                profile=profile,
                reason=reason,
            )
        except OSError as exc:
            raise HookDispatcherError(f"bypass audit is not writable: {exc}") from exc
        sys.stderr.write(
            json.dumps(
                {
                    "status": "bypassed",
                    "event_type": event_type,
                    "reason": reason,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 0

    diagnostics: list[dict[str, object]] = []
    returncodes: list[int] = []
    if enabled:
        runtime_rc, runtime_diagnostics = _runtime_result(payload, context, record, event_dir)
        returncodes.append(runtime_rc)
        diagnostics.extend(runtime_diagnostics)
    approved_rcs, approved_diagnostics = _approved_results(
        hook_name, hook_args, stdin_bytes, context, record, event_dir
    )
    returncodes.extend(approved_rcs)
    diagnostics.extend(approved_diagnostics)

    if hook_name in {"pre-commit", "commit-msg"}:
        try:
            if _index_tree(context) != index_before or _worktree_fingerprint(context) != worktree_before:
                returncodes.insert(0, 1)
                diagnostics.insert(
                    0,
                    _diagnostic(
                        source="dispatcher",
                        exit_code=1,
                        message=(
                            "commit gate modified the index or working tree; review and stage the intended content before retrying"
                        ),
                        log_ref=None,
                    ),
                )
        except HookDispatcherError as exc:
            returncodes.insert(0, 1)
            diagnostics.insert(
                0,
                _diagnostic(
                    source="dispatcher",
                    exit_code=1,
                    message=str(exc),
                    log_ref=None,
                ),
            )

    failures = [code for code in returncodes if code != 0]
    if diagnostics:
        _emit_diagnostics(
            diagnostics,
            status="blocked" if blocking and failures else "diagnosed",
        )
    if not failures:
        return 0
    if blocking:
        return failures[0]
    return 0


def _cleanup_ephemeral_event_state(event_dir: Path) -> None:
    shutil.rmtree(event_dir / "staged", ignore_errors=True)
    for name in ("pre-push-stdin.txt", "rewrite-stdin.txt"):
        (event_dir / name).unlink(missing_ok=True)
    try:
        event_dir.rmdir()
    except OSError:
        pass


def dispatch(
    context: GitContext,
    *,
    state_root: Path,
    hook_name: str,
    hook_args: Sequence[str],
    stdin_bytes: bytes,
) -> int:
    if hook_name not in HOOK_EVENTS:
        raise HookDispatcherError(f"unsupported hook: {hook_name}")
    record = _load_record(state_root, context)
    configured = _git_config_get(context, "core.hooksPath")
    if configured != record.get("hooks_path"):
        raise HookDispatcherError("core.hooksPath does not match trusted installation")
    payload, event_dir, index_before, worktree_before = _event_payload(
        hook_name, hook_args, stdin_bytes, context, record
    )
    try:
        return _dispatch_prepared_event(
            context,
            record=record,
            hook_name=hook_name,
            hook_args=hook_args,
            stdin_bytes=stdin_bytes,
            payload=payload,
            event_dir=event_dir,
            index_before=index_before,
            worktree_before=worktree_before,
        )
    finally:
        _cleanup_ephemeral_event_state(event_dir)


def doctor(context: GitContext, *, install_root: Path, state_root: Path) -> dict[str, object]:
    record_path = _record_path(state_root, context)
    record: dict[str, Any] | None = None
    if record_path.is_file():
        record = _load_record(state_root, context)
    current = install_root.expanduser().resolve(strict=False) / "current"
    configured = _git_config_get(context, "core.hooksPath")
    expected = record.get("hooks_path") if record else None
    current_release = current.resolve(strict=False) if current.exists() else None
    bundle_metadata: dict[str, Any] = {}
    bundle_metadata_valid = False
    if current_release is not None:
        try:
            bundle_metadata = _read_bundle_metadata(current_release)
            bundle_metadata_valid = True
        except HookDispatcherError:
            bundle_metadata = {}
    runtime_path = current / "lib" / "agent_runtime.py"
    bundle_python = Path(str(bundle_metadata.get("python") or ""))
    bundle_python_available = (
        bundle_python.is_absolute()
        and bundle_python.is_file()
        and os.access(bundle_python, os.X_OK)
    )
    registry_path = Path(str(record.get("registry_path"))) if record else None
    hook_health = {
        hook_name: {
            "path": str(current / "hooks" / hook_name),
            "executable": (current / "hooks" / hook_name).is_file()
            and os.access(current / "hooks" / hook_name, os.X_OK),
        }
        for hook_name in HOOK_EVENTS
    }
    management_raw = (
        _git_config_get(context, "agent.runtime.managementCheckout") or ""
    ).lower()
    management_config_valid = management_raw in {"", "true", "false"}
    management_checkout = management_raw == "true"
    primary_checkout = not context.is_linked_worktree and not context.is_submodule
    effective_check_scope = (
        "repo+machine"
        if management_checkout and primary_checkout
        else "repo-only"
    )
    approved_health: list[dict[str, object]] = []
    if record:
        for hook_name, entries in (record.get("approved_hooks") or {}).items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                path = Path(str(entry.get("trusted_path") or ""))
                approved_health.append(
                    {
                        "event": hook_name,
                        "path": str(path),
                        "digest_matches": path.is_file()
                        and _sha256_file(path) == entry.get("sha256"),
                        "executable": path.is_file() and os.access(path, os.X_OK),
                    }
                )
    healthy = bool(
        record
        and configured == expected
        and current_release is not None
        and bundle_metadata_valid
        and bundle_metadata.get("state_root") == record.get("state_root")
        and bundle_python_available
        and runtime_path.is_file()
        and registry_path is not None
        and registry_path.is_file()
        and all(item["executable"] for item in hook_health.values())
        and management_config_valid
        and all(
            item["digest_matches"] and item["executable"]
            for item in approved_health
        )
    )
    return {
        "schema_version": INSTALL_SCHEMA_VERSION,
        "repository_id": context.repository_id,
        "worktree_id": context.worktree_id,
        "installed": record is not None,
        "healthy": healthy,
        "management_checkout": management_checkout,
        "management_checkout_config_valid": management_config_valid,
        "effective_check_scope": effective_check_scope,
        "installation_record": str(record_path),
        "configured_hooks_path": configured,
        "expected_hooks_path": expected,
        "hooks_path_matches": configured == expected if record else False,
        "bundle_current": str(current_release) if current_release else None,
        "bundle_matches_record": (
            str(current_release) == record.get("release")
            if current_release is not None and record
            else False
        ),
        "bundle_metadata_valid": bundle_metadata_valid,
        "bundle_state_root": bundle_metadata.get("state_root"),
        "bundle_state_matches_record": (
            bundle_metadata.get("state_root") == record.get("state_root")
            if bundle_metadata_valid and record
            else False
        ),
        "trusted_python": str(bundle_python) if bundle_metadata.get("python") else None,
        "trusted_python_available": bundle_python_available,
        "runtime_path": str(runtime_path),
        "runtime_available": runtime_path.is_file(),
        "registry_path": str(registry_path) if registry_path else None,
        "registry_available": registry_path.is_file() if registry_path else False,
        "bypass_audit_path": record.get("bypass_audit_path") if record else None,
        "hooks": hook_health,
        "approved_hooks": approved_health,
    }


def _default_install_root() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    return base / "mac-bootstrap-agent-runtime" / "git-hooks"


def _default_state_root() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()
    return base / "mac-bootstrap-agent-runtime" / "git-hooks"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-git-hook-dispatcher")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--install-root", type=Path, default=_default_install_root())
    parser.add_argument("--state-root", type=Path, default=_default_state_root())
    parser.add_argument("--python", type=Path, default=_default_trusted_python())
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--registry", type=Path, required=True)
    install_parser.add_argument("--approve-hook", action="append", default=[])
    subparsers.add_parser("uninstall")
    subparsers.add_parser("inventory")
    subparsers.add_parser("doctor")
    dispatch_parser = subparsers.add_parser("dispatch")
    dispatch_parser.add_argument("hook_name", choices=tuple(HOOK_EVENTS))
    dispatch_parser.add_argument("hook_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        context = resolve_git_context(args.repo)
        if args.command == "install":
            print(
                _json(
                    install(
                        context,
                        registry=args.registry,
                        install_root=args.install_root,
                        state_root=args.state_root,
                        trusted_python=args.python,
                        approved_specs=args.approve_hook,
                    )
                )
            )
            return 0
        if args.command == "uninstall":
            print(_json(uninstall(context, state_root=args.state_root)))
            return 0
        if args.command == "inventory":
            print(_json(inventory(context, args.state_root)))
            return 0
        if args.command == "doctor":
            print(
                _json(
                    doctor(
                        context,
                        install_root=args.install_root,
                        state_root=args.state_root,
                    )
                )
            )
            return 0
        if args.command == "dispatch":
            return dispatch(
                context,
                state_root=args.state_root,
                hook_name=args.hook_name,
                hook_args=args.hook_args,
                stdin_bytes=sys.stdin.buffer.read(),
            )
        raise HookDispatcherError(f"unsupported command: {args.command}")
    except (HookDispatcherError, GitContextError, OSError, ValueError) as exc:
        message = exc.message if isinstance(exc, GitContextError) else str(exc)
        print(f"ERROR: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
