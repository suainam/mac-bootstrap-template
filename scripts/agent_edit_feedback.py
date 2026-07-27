#!/usr/bin/env python3
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any, Iterator, Mapping, Sequence

from agent_git_context import GitContext, RuntimeStatePaths


ACCUMULATOR_SCHEMA_VERSION = 1
DIAGNOSTIC_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = 1
MAX_SAFE_FIX_ROUNDS = 5


class FeedbackStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileSnapshot:
    exists: bool
    data: bytes
    mode: int | None


@dataclass(frozen=True)
class GateExecutionResult:
    diagnostic: dict[str, object] | None = None
    changed: bool = False
    skipped: bool = False
    receipt_path: Path | None = None


def _normalized_message(message: str) -> str:
    return " ".join(message.split())[:1024]


def _sanitize(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return result or "item"


def _sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def file_content_hash(path: Path) -> str:
    try:
        if path.is_file():
            return _sha256_bytes(path.read_bytes())
        if path.exists():
            return "non-file"
        return "missing"
    except OSError as exc:
        return f"unreadable:{exc.errno or 'unknown'}"


def target_content_hash(repo_root: Path, target_paths: Sequence[str]) -> str:
    material = {
        path: file_content_hash(repo_root / path)
        for path in sorted(set(target_paths))
    }
    rendered = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_bytes(rendered.encode("utf-8"))


def snapshot_targets(repo_root: Path, target_paths: Sequence[str]) -> dict[str, FileSnapshot]:
    snapshots: dict[str, FileSnapshot] = {}
    for relative in sorted(set(target_paths)):
        path = repo_root / relative
        if path.is_file():
            stat = path.stat()
            snapshots[relative] = FileSnapshot(
                exists=True,
                data=path.read_bytes(),
                mode=stat.st_mode & 0o777,
            )
        elif path.exists():
            raise FeedbackStateError(f"target is not a regular file: {relative}")
        else:
            snapshots[relative] = FileSnapshot(exists=False, data=b"", mode=None)
    return snapshots


def restore_targets(repo_root: Path, snapshots: Mapping[str, FileSnapshot]) -> None:
    failures: list[str] = []
    for relative, snapshot in snapshots.items():
        path = repo_root / relative
        try:
            if snapshot.exists:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(snapshot.data)
                if snapshot.mode is not None:
                    path.chmod(snapshot.mode)
            elif path.exists():
                if path.is_file() or path.is_symlink():
                    path.unlink()
                else:
                    failures.append(relative)
        except OSError:
            failures.append(relative)
    if failures:
        raise FeedbackStateError(
            "could not restore modified targets: " + ", ".join(sorted(failures))
        )


def targets_changed(repo_root: Path, snapshots: Mapping[str, FileSnapshot]) -> bool:
    for relative, snapshot in snapshots.items():
        path = repo_root / relative
        if snapshot.exists != path.is_file():
            return True
        if snapshot.exists and file_content_hash(path) != _sha256_bytes(snapshot.data):
            return True
    return False


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeedbackStateError(f"invalid runtime state file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FeedbackStateError(f"runtime state file must be an object: {path}")
    return payload


@contextmanager
def exclusive_lock(path: Path, timeout_seconds: float) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise FeedbackStateError(f"lock timed out: {path}")
                time.sleep(0.02)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _state_probe(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=".write-probe-", dir=directory)
    probe = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
        probe.unlink(missing_ok=True)


def ensure_safe_fix_state(state_paths: RuntimeStatePaths) -> None:
    try:
        _state_probe(state_paths.diagnostics_dir)
        _state_probe(state_paths.receipts_dir)
        _state_probe(state_paths.worktree_dir / "locks")
    except OSError as exc:
        raise FeedbackStateError(f"runtime state is not writable: {exc}") from exc


def diagnostic_fingerprint(
    *,
    gate_id: str,
    severity: str,
    action: str,
    message: str,
    content_hash: str,
    rule_revision: str,
) -> str:
    material = json.dumps(
        {
            "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "gate_id": gate_id,
            "severity": severity,
            "action": action,
            "message": _normalized_message(message),
            "content_hash": content_hash,
            "rule_revision": rule_revision,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"diag-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def make_diagnostic(
    *,
    gate_id: str,
    severity: str,
    action: str,
    message: str,
    content_hash: str,
    rule_revision: str,
    evidence: Sequence[str] = (),
    log_ref: Path | None = None,
) -> dict[str, object]:
    normalized = _normalized_message(message)
    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "gate_id": gate_id,
        "severity": severity,
        "action": action,
        "message": normalized,
        "evidence": list(evidence),
        "log_ref": str(log_ref) if log_ref else None,
        "content_hash": content_hash,
        "rule_revision": rule_revision,
        "fingerprint": diagnostic_fingerprint(
            gate_id=gate_id,
            severity=severity,
            action=action,
            message=normalized,
            content_hash=content_hash,
            rule_revision=rule_revision,
        ),
    }


def _diagnostic_index_path(state_paths: RuntimeStatePaths) -> Path:
    return state_paths.diagnostics_dir / "seen-diagnostics.json"


def filter_new_diagnostics(
    diagnostics: Sequence[Mapping[str, object]],
    state_paths: RuntimeStatePaths | None,
) -> list[dict[str, object]]:
    normalized = [dict(item) for item in diagnostics]
    if not normalized or state_paths is None:
        return normalized
    index_path = _diagnostic_index_path(state_paths)
    lock_path = state_paths.session_dir / "diagnostics.lock"
    try:
        with exclusive_lock(lock_path, 2.0):
            payload = _read_json(index_path)
            seen_raw = payload.get("fingerprints", [])
            seen = {
                item for item in seen_raw if isinstance(item, str)
            } if isinstance(seen_raw, list) else set()
            fresh = [
                item
                for item in normalized
                if isinstance(item.get("fingerprint"), str)
                and item["fingerprint"] not in seen
            ]
            seen.update(
                str(item["fingerprint"])
                for item in normalized
                if isinstance(item.get("fingerprint"), str)
            )
            _atomic_write_json(
                index_path,
                {
                    "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
                    "fingerprints": sorted(seen)[-2048:],
                },
            )
            return fresh
    except (OSError, FeedbackStateError):
        return normalized


def _accumulator_payload(
    context: GitContext,
    session_id: str,
    changed_files: Mapping[str, str],
) -> dict[str, object]:
    return {
        "schema_version": ACCUMULATOR_SCHEMA_VERSION,
        "repository_id": context.repository_id,
        "worktree_id": context.worktree_id,
        "session_id": session_id,
        "changed_files": dict(sorted(changed_files.items())),
        "updated_at_ns": time.time_ns(),
    }


def record_changed_files(
    *,
    context: GitContext,
    state_paths: RuntimeStatePaths,
    session_id: str,
    repo_root: Path,
    target_paths: Sequence[str],
) -> None:
    if not target_paths:
        return
    try:
        with exclusive_lock(state_paths.lock_path, 2.0):
            current = _read_json(state_paths.accumulator_path)
            changed_raw = current.get("changed_files", {})
            changed = {
                key: value
                for key, value in changed_raw.items()
                if isinstance(key, str) and isinstance(value, str)
            } if isinstance(changed_raw, dict) else {}
            for relative in sorted(set(target_paths)):
                changed[relative] = file_content_hash(repo_root / relative)
            _atomic_write_json(
                state_paths.accumulator_path,
                _accumulator_payload(context, session_id, changed),
            )
    except OSError as exc:
        raise FeedbackStateError(f"could not update changed-file accumulator: {exc}") from exc


def accumulated_paths(
    *,
    context: GitContext,
    state_paths: RuntimeStatePaths,
) -> tuple[str, ...]:
    try:
        with exclusive_lock(state_paths.lock_path, 2.0):
            payload = _read_json(state_paths.accumulator_path)
    except OSError as exc:
        raise FeedbackStateError(f"could not read changed-file accumulator: {exc}") from exc
    if not payload:
        return ()
    if (
        payload.get("repository_id") != context.repository_id
        or payload.get("worktree_id") != context.worktree_id
    ):
        raise FeedbackStateError("changed-file accumulator scope does not match Git context")
    changed = payload.get("changed_files", {})
    if not isinstance(changed, dict):
        raise FeedbackStateError("changed-file accumulator changed_files must be an object")
    return tuple(sorted(key for key in changed if isinstance(key, str)))


def clear_accumulator(state_paths: RuntimeStatePaths) -> None:
    try:
        with exclusive_lock(state_paths.lock_path, 2.0):
            state_paths.accumulator_path.unlink(missing_ok=True)
    except OSError as exc:
        raise FeedbackStateError(f"could not clear changed-file accumulator: {exc}") from exc


def _log_path(
    state_paths: RuntimeStatePaths,
    event_id: str,
    gate_id: str,
) -> Path:
    stem = f"{_sanitize(event_id)}-{_sanitize(gate_id)}-{time.time_ns()}"
    return state_paths.diagnostics_dir / f"{stem}.log"


def _write_gate_log(
    path: Path,
    *,
    command: Sequence[str],
    stdout: str,
    stderr: str,
    returncode: int | None,
    note: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "command=" + json.dumps(list(command), ensure_ascii=False),
        f"returncode={returncode if returncode is not None else 'timeout'}",
    ]
    if note:
        lines.append(f"note={note}")
    if stdout:
        lines.extend(["--- stdout ---", stdout.rstrip()])
    if stderr:
        lines.extend(["--- stderr ---", stderr.rstrip()])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def run_guarded_check(
    *,
    gate_id: str,
    command: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: float,
    repo_root: Path,
    target_paths: Sequence[str],
    state_paths: RuntimeStatePaths | None,
    event_id: str,
    severity: str,
    rule_revision: str,
    include_output: bool,
) -> GateExecutionResult:
    before_hash = target_content_hash(repo_root, target_paths)
    try:
        snapshots = snapshot_targets(repo_root, target_paths)
    except (OSError, FeedbackStateError) as exc:
        return GateExecutionResult(
            diagnostic=make_diagnostic(
                gate_id=gate_id,
                severity=severity,
                action="fix",
                message=f"could not snapshot target files: {exc}",
                content_hash=before_hash,
                rule_revision=rule_revision,
                evidence=target_paths,
            )
        )
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(env),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        result = subprocess.CompletedProcess(
            args=list(command),
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
        )
        timed_out = True
    except OSError as exc:
        result = subprocess.CompletedProcess(
            args=list(command),
            returncode=127,
            stdout="",
            stderr=str(exc),
        )
        timed_out = False

    mutation = targets_changed(repo_root, snapshots)
    log_ref: Path | None = None
    if mutation or result.returncode != 0:
        if state_paths is not None:
            candidate = _log_path(state_paths, event_id, gate_id)
            try:
                _write_gate_log(
                    candidate,
                    command=command,
                    stdout=str(result.stdout or ""),
                    stderr=str(result.stderr or ""),
                    returncode=None if timed_out else result.returncode,
                    note="unapproved target mutation restored" if mutation else None,
                )
                log_ref = candidate
            except OSError:
                log_ref = None

    if mutation:
        try:
            restore_targets(repo_root, snapshots)
            message = "check gate modified target files; runtime restored the original content"
        except FeedbackStateError as exc:
            message = f"check gate modified target files and restoration failed: {exc}"
        return GateExecutionResult(
            diagnostic=make_diagnostic(
                gate_id=gate_id,
                severity=severity,
                action="restore-unapproved-mutation",
                message=message,
                content_hash=before_hash,
                rule_revision=rule_revision,
                evidence=target_paths,
                log_ref=log_ref,
            )
        )
    if result.returncode == 0:
        return GateExecutionResult()

    detail = ""
    if include_output:
        detail = str(result.stderr or "").strip() or str(result.stdout or "").strip()
    if timed_out:
        message = f"gate timed out after {timeout_seconds:g}s"
    else:
        message = f"gate failed with exit code {result.returncode}"
    if detail:
        message += f": {detail}"
    return GateExecutionResult(
        diagnostic=make_diagnostic(
            gate_id=gate_id,
            severity=severity,
            action="fix",
            message=message,
            content_hash=before_hash,
            rule_revision=rule_revision,
            evidence=target_paths,
            log_ref=log_ref,
        )
    )


def _receipt_path(
    state_paths: RuntimeStatePaths,
    relative_path: str,
    operation_id: str,
) -> Path:
    digest = hashlib.sha256(
        f"{relative_path}\0{operation_id}".encode("utf-8")
    ).hexdigest()[:24]
    return state_paths.receipts_dir / f"{_sanitize(operation_id)}-{digest}.json"


def _file_lock_path(
    state_paths: RuntimeStatePaths,
    relative_path: str,
) -> Path:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:24]
    return state_paths.worktree_dir / "locks" / f"file-{digest}.lock"


def run_safe_fix(
    *,
    gate_id: str,
    command: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: float,
    repo_root: Path,
    target_path: str,
    state_paths: RuntimeStatePaths,
    event_id: str,
    operation_id: str,
    max_rounds: int,
    severity: str,
    rule_revision: str,
    include_output: bool,
) -> GateExecutionResult:
    target = repo_root / target_path
    before_hash = file_content_hash(target)
    try:
        ensure_safe_fix_state(state_paths)
    except FeedbackStateError as exc:
        return GateExecutionResult(
            diagnostic=make_diagnostic(
                gate_id=gate_id,
                severity=severity,
                action="stop-safe-fix",
                message=str(exc),
                content_hash=before_hash,
                rule_revision=rule_revision,
                evidence=[target_path],
            )
        )

    receipt_path = _receipt_path(state_paths, target_path, operation_id)
    lock_path = _file_lock_path(state_paths, target_path)
    try:
        with exclusive_lock(lock_path, timeout_seconds):
            before_hash = file_content_hash(target)
            existing = _read_json(receipt_path)
            if (
                existing.get("schema_version") == RECEIPT_SCHEMA_VERSION
                and existing.get("operation_id") == operation_id
                and existing.get("rule_revision") == rule_revision
                and existing.get("output_content_hash") == before_hash
            ):
                return GateExecutionResult(
                    skipped=True,
                    receipt_path=receipt_path,
                )
            snapshots = snapshot_targets(repo_root, [target_path])
            log_ref = _log_path(state_paths, event_id, gate_id)
            current_hash = before_hash
            changed = False
            for round_number in range(1, max_rounds + 1):
                round_env = dict(env)
                round_env.update(
                    {
                        "AGENT_RUNTIME_SAFE_FIX_OPERATION_ID": operation_id,
                        "AGENT_RUNTIME_SAFE_FIX_ROUND": str(round_number),
                        "AGENT_RUNTIME_SAFE_FIX_MAX_ROUNDS": str(max_rounds),
                        "AGENT_RUNTIME_EXPECTED_CONTENT_HASH": current_hash,
                    }
                )
                try:
                    result = subprocess.run(
                        list(command),
                        cwd=cwd,
                        env=round_env,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=timeout_seconds,
                    )
                    timed_out = False
                except subprocess.TimeoutExpired as exc:
                    result = subprocess.CompletedProcess(
                        args=list(command),
                        returncode=124,
                        stdout=exc.stdout or "",
                        stderr=exc.stderr or "",
                    )
                    timed_out = True
                except OSError as exc:
                    result = subprocess.CompletedProcess(
                        args=list(command),
                        returncode=127,
                        stdout="",
                        stderr=str(exc),
                    )
                    timed_out = False

                try:
                    _write_gate_log(
                        log_ref,
                        command=command,
                        stdout=str(result.stdout or ""),
                        stderr=str(result.stderr or ""),
                        returncode=None if timed_out else result.returncode,
                        note=f"safe-fix round {round_number}/{max_rounds}",
                    )
                except OSError as exc:
                    restore_targets(repo_root, snapshots)
                    return GateExecutionResult(
                        diagnostic=make_diagnostic(
                            gate_id=gate_id,
                            severity=severity,
                            action="stop-safe-fix",
                            message=f"runtime state log is not writable: {exc}",
                            content_hash=before_hash,
                            rule_revision=rule_revision,
                            evidence=[target_path],
                        )
                    )

                if result.returncode != 0:
                    restore_targets(repo_root, snapshots)
                    detail = ""
                    if include_output:
                        detail = str(result.stderr or "").strip() or str(result.stdout or "").strip()
                    message = (
                        f"safe-fix timed out after {timeout_seconds:g}s"
                        if timed_out
                        else f"safe-fix failed with exit code {result.returncode}"
                    )
                    if detail:
                        message += f": {detail}"
                    return GateExecutionResult(
                        diagnostic=make_diagnostic(
                            gate_id=gate_id,
                            severity=severity,
                            action="stop-safe-fix",
                            message=message,
                            content_hash=before_hash,
                            rule_revision=rule_revision,
                            evidence=[target_path],
                            log_ref=log_ref,
                        )
                    )

                after_hash = file_content_hash(target)
                if after_hash == current_hash:
                    receipt = {
                        "schema_version": RECEIPT_SCHEMA_VERSION,
                        "event_id": event_id,
                        "gate_id": gate_id,
                        "operation_id": operation_id,
                        "rule_revision": rule_revision,
                        "target_path": target_path,
                        "input_content_hash": before_hash,
                        "output_content_hash": after_hash,
                        "rounds": round_number,
                        "changed": changed,
                        "log_ref": None,
                        "created_at_ns": time.time_ns(),
                    }
                    try:
                        _atomic_write_json(receipt_path, receipt)
                    except OSError as exc:
                        restore_targets(repo_root, snapshots)
                        return GateExecutionResult(
                            diagnostic=make_diagnostic(
                                gate_id=gate_id,
                                severity=severity,
                                action="stop-safe-fix",
                                message=f"runtime state receipt is not writable: {exc}",
                                content_hash=before_hash,
                                rule_revision=rule_revision,
                                evidence=[target_path],
                                log_ref=log_ref,
                            )
                        )
                    log_ref.unlink(missing_ok=True)
                    return GateExecutionResult(
                        changed=changed,
                        receipt_path=receipt_path,
                    )
                changed = True
                current_hash = after_hash

            restore_targets(repo_root, snapshots)
            return GateExecutionResult(
                diagnostic=make_diagnostic(
                    gate_id=gate_id,
                    severity=severity,
                    action="stop-safe-fix",
                    message=f"safe-fix did not become idempotent within {max_rounds} rounds; original content restored",
                    content_hash=before_hash,
                    rule_revision=rule_revision,
                    evidence=[target_path],
                    log_ref=log_ref,
                )
            )
    except (OSError, FeedbackStateError) as exc:
        return GateExecutionResult(
            diagnostic=make_diagnostic(
                gate_id=gate_id,
                severity=severity,
                action="stop-safe-fix",
                message=f"safe-fix state or lock failure: {exc}",
                content_hash=before_hash,
                rule_revision=rule_revision,
                evidence=[target_path],
            )
        )
