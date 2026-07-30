#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from typing import Any, Mapping, Sequence

from agent_git_context import (
    GitContext,
    GitContextError,
    clean_git_local_environment,
    resolve_git_context,
)
from agent_git_hook_dispatcher import (
    EVENT_SCHEMA_VERSION,
    PUSH_RECEIPT_SCHEMA_VERSION,
    ZERO_OID,
    HookDispatcherError,
    _atomic_write_json,
    _cleanup_ephemeral_event_state,
    _diagnostic,
    _emit_diagnostics,
    _event_state_dir,
    _git_config_get,
    _json,
    _load_record,
    _profile,
    _push_state_paths,
    _run,
    _runtime_result,
    _validate_push_operation_id,
)


def _default_state_root() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()
    return base / "mac-bootstrap-agent-runtime" / "git-hooks"


def _read_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HookDispatcherError(f"{description} does not exist: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HookDispatcherError(f"invalid {description}: {exc}") from exc
    if not isinstance(payload, dict):
        raise HookDispatcherError(f"invalid {description}: expected a JSON object")
    return payload


def _receipt_candidates(
    record: Mapping[str, Any],
    context: GitContext,
    operation_id: str | None,
) -> list[Path]:
    worktree_dir = context.runtime_state_paths(
        "push-receipt-query",
        Path(str(record["state_root"])),
    ).worktree_dir
    pattern = (
        f"sessions/*/receipts/push-success-{_validate_push_operation_id(operation_id)}.json"
        if operation_id and operation_id != "latest"
        else "sessions/*/receipts/push-success-*.json"
    )
    return sorted(
        worktree_dir.glob(pattern),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )


def _query_receipt(
    record: Mapping[str, Any],
    context: GitContext,
    operation_id: str,
) -> dict[str, Any]:
    candidates = _receipt_candidates(record, context, operation_id)
    if not candidates:
        raise HookDispatcherError(f"push receipt not found: {operation_id}")
    payload = _read_json_object(candidates[0], "push receipt")
    if payload.get("schema_version") != PUSH_RECEIPT_SCHEMA_VERSION:
        raise HookDispatcherError("unsupported push receipt schema")
    return payload


def _parse_args(
    argv: Sequence[str],
) -> tuple[str | None, str | None, bool, list[str]]:
    operation_id: str | None = None
    receipt_query: str | None = None
    explain = False
    git_args: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--":
            git_args = list(argv[index + 1 :])
            break
        if value == "--operation-id":
            index += 1
            if index >= len(argv):
                raise HookDispatcherError("--operation-id requires a value")
            operation_id = _validate_push_operation_id(argv[index])
            index += 1
            continue
        if value == "--receipt":
            index += 1
            if index >= len(argv):
                raise HookDispatcherError("--receipt requires an operation ID or latest")
            receipt_query = argv[index]
            index += 1
            continue
        if value == "--explain":
            explain = True
            index += 1
            continue
        if value in {"-h", "--help"}:
            print(
                "usage: agent-git-push [--operation-id ID] [git push args...]\n"
                "       agent-git-push --receipt ID|latest\n"
                "       agent-git-push --explain"
            )
            return None, None, False, []
        git_args = list(argv[index:])
        break
    modes = int(receipt_query is not None) + int(explain)
    if modes > 1:
        raise HookDispatcherError("--receipt and --explain are mutually exclusive")
    if modes and git_args:
        raise HookDispatcherError("receipt/explain mode does not accept git push arguments")
    return operation_id, receipt_query, explain, git_args


def _remote_ref_map(
    context: GitContext,
    remote: str,
    remote_refs: Sequence[str],
) -> dict[str, str]:
    if not remote:
        raise HookDispatcherError("push plan has no remote name or URL")
    result = _run(
        ["git", "ls-remote", "--refs", remote, *remote_refs],
        cwd=context.cwd,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise HookDispatcherError(detail or "cannot verify remote refs after push")
    refs: dict[str, str] = {}
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        oid, separator, ref = line.partition("\t")
        if separator and len(oid) == 40 and ref:
            refs[ref] = oid.lower()
    return refs


def _verified_refs(
    context: GitContext,
    plan: Mapping[str, Any],
) -> list[dict[str, object]]:
    raw_refs = plan.get("refs")
    if not isinstance(raw_refs, list) or not raw_refs:
        raise HookDispatcherError("push plan contains no ref updates")
    remote_refs: list[str] = []
    for raw_ref in raw_refs:
        if not isinstance(raw_ref, Mapping):
            raise HookDispatcherError("push plan ref entry is invalid")
        remote_ref = raw_ref.get("remote_ref")
        if not isinstance(remote_ref, str) or not remote_ref:
            raise HookDispatcherError("push plan remote ref is invalid")
        remote_refs.append(remote_ref)
    remote = str(plan.get("remote_url") or plan.get("remote_name") or "")
    observed = _remote_ref_map(context, remote, remote_refs)
    verified: list[dict[str, object]] = []
    for raw_ref in raw_refs:
        local_oid = str(raw_ref.get("local_oid") or "").lower()
        remote_ref = str(raw_ref["remote_ref"])
        deleted = local_oid == ZERO_OID
        remote_after = observed.get(remote_ref, ZERO_OID)
        if deleted:
            if remote_after != ZERO_OID:
                raise HookDispatcherError(
                    f"remote ref still exists after deletion push: {remote_ref}"
                )
        elif remote_after != local_oid:
            raise HookDispatcherError(
                f"remote ref does not match pushed OID: {remote_ref}"
            )
        verified.append(
            {
                "local_ref": raw_ref.get("local_ref"),
                "local_oid": local_oid,
                "remote_ref": remote_ref,
                "remote_oid_before": str(raw_ref.get("remote_oid") or "").lower(),
                "remote_oid_after": remote_after,
                "force_update": bool(raw_ref.get("force_update")),
                "deleted": deleted,
            }
        )
    return verified


def _write_log(
    path: Path,
    *,
    operation_id: str,
    git_args: Sequence[str],
    started_at: str,
    completed_at: str | None,
    returncode: int | None,
    git_trace_ref: str,
) -> None:
    _atomic_write_json(
        path,
        {
            "schema_version": PUSH_RECEIPT_SCHEMA_VERSION,
            "operation_id": operation_id,
            "git_args": list(git_args),
            "started_at": started_at,
            "completed_at": completed_at,
            "returncode": returncode,
            "git_trace_ref": git_trace_ref,
        },
    )


def _explain(
    record: Mapping[str, Any],
    context: GitContext,
) -> dict[str, object]:
    state_paths = context.runtime_state_paths(
        "push-explain",
        Path(str(record["state_root"])),
    )
    return {
        "schema_version": PUSH_RECEIPT_SCHEMA_VERSION,
        "repository_id": context.repository_id,
        "worktree_id": context.worktree_id,
        "repo_root": str(context.repo_root or context.cwd),
        "profile": _profile(context)[1],
        "runtime_release": record.get("release"),
        "receipt_search_root": str(state_paths.worktree_dir / "sessions"),
    }


def _maybe_test_failure(point: str) -> None:
    if (
        os.environ.get("AGENT_RUNTIME_TESTING") == "1"
        and os.environ.get("AGENT_RUNTIME_PUSH_FAIL_AT") == point
    ):
        raise HookDispatcherError(f"simulated push receipt failure at {point}")


def _finalize_success(
    context: GitContext,
    record: Mapping[str, Any],
    *,
    operation_id: str,
    session_id: str,
    git_args: Sequence[str],
    pending_path: Path,
    receipt_path: Path,
    log_path: Path,
    started_at: str,
    completed_at: str,
) -> int:
    plan = _read_json_object(pending_path, "pending push plan")
    if (
        plan.get("operation_id") != operation_id
        or plan.get("session_id") != session_id
        or plan.get("repository_id") != context.repository_id
        or plan.get("worktree_id") != context.worktree_id
        or plan.get("git_args") != list(git_args)
    ):
        raise HookDispatcherError("pending push plan identity mismatch")
    verified_refs = _verified_refs(context, plan)
    dispatched = plan.get("push_success_dispatched") is True
    existing_event_id = plan.get("push_success_event_id")
    event_id = (
        existing_event_id
        if dispatched and isinstance(existing_event_id, str) and existing_event_id
        else f"push-success-{uuid.uuid4().hex}"
    )
    if not dispatched:
        payload = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_type": "push.success",
            "event_id": event_id,
            "source_adapter": "git-push-wrapper",
            "timestamp": completed_at,
            "cwd": str(context.repo_root),
            "target_paths": [],
            "session_id": session_id,
            "metadata": {
                "operation_id": operation_id,
                "remote_name": plan.get("remote_name", ""),
                "remote_url": plan.get("remote_url", ""),
                "refs": verified_refs,
                "log_ref": str(log_path),
            },
        }
        event_dir = _event_state_dir(record, context, event_id)
        try:
            runtime_rc, diagnostics = _runtime_result(payload, context, record, event_dir)
        finally:
            _cleanup_ephemeral_event_state(event_dir)
        if runtime_rc != 0 or diagnostics:
            _emit_diagnostics(diagnostics, status="push-succeeded-receipt-failed")
            return runtime_rc or 2
        plan["push_success_dispatched"] = True
        plan["push_success_event_id"] = event_id
        _atomic_write_json(pending_path, plan)
    push_log = _read_json_object(log_path, "push log")
    receipt = {
        "schema_version": PUSH_RECEIPT_SCHEMA_VERSION,
        "event_type": "push.success",
        "event_id": event_id,
        "operation_id": operation_id,
        "session_id": session_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "repository_id": context.repository_id,
        "worktree_id": context.worktree_id,
        "repo_root": str(context.repo_root),
        "profile": plan.get("profile"),
        "runtime_release": plan.get("runtime_release"),
        "remote_name": plan.get("remote_name", ""),
        "remote_url": plan.get("remote_url", ""),
        "git_args": list(git_args),
        "refs": verified_refs,
        "log_ref": str(log_path),
        "git_trace_ref": str(push_log.get("git_trace_ref") or ""),
    }
    _maybe_test_failure("before-receipt-write")
    _atomic_write_json(receipt_path, receipt)
    pending_path.unlink(missing_ok=True)
    return 0


def _report_receipt_failure(log_path: Path, error: BaseException) -> int:
    diagnostic = _diagnostic(
        source="push-wrapper",
        exit_code=2,
        message=(
            "remote push succeeded but push.success receipt was not completed; "
            f"remote may already be updated: {error}"
        ),
        log_ref=log_path,
    )
    _emit_diagnostics(
        [diagnostic],
        status="push-succeeded-receipt-failed",
    )
    return 2


def push(
    context: GitContext,
    *,
    state_root: Path,
    argv: Sequence[str],
) -> int:
    if context.repo_root is None:
        raise HookDispatcherError("push wrapper requires a non-bare worktree")
    record = _load_record(state_root, context)
    configured = _git_config_get(context, "core.hooksPath")
    if configured != record.get("hooks_path"):
        raise HookDispatcherError("core.hooksPath does not match trusted installation")
    operation_id, receipt_query, explain, git_args = _parse_args(argv)
    if receipt_query is not None:
        print(_json(_query_receipt(record, context, receipt_query)))
        return 0
    if explain:
        print(_json(_explain(record, context)))
        return 0
    if "--no-verify" in git_args:
        raise HookDispatcherError(
            "push wrapper does not support --no-verify because a verified pre-push plan is required"
        )
    if operation_id is None:
        operation_id = uuid.uuid4().hex
    session_id = os.environ.get("AGENT_RUNTIME_SESSION_ID") or f"push-{operation_id}"
    pending_path, receipt_path, log_path = _push_state_paths(
        record,
        context,
        session_id,
        operation_id,
    )
    existing = _receipt_candidates(record, context, operation_id)
    if existing:
        receipt = _read_json_object(existing[0], "push receipt")
        if receipt.get("git_args") != list(git_args):
            raise HookDispatcherError(
                "push operation ID already belongs to different git arguments"
            )
        _verified_refs(context, receipt)
        return 0

    if pending_path.is_file() and log_path.is_file():
        previous_log = _read_json_object(log_path, "push log")
        previous_started = previous_log.get("started_at")
        previous_completed = previous_log.get("completed_at")
        if (
            previous_log.get("operation_id") == operation_id
            and previous_log.get("git_args") == list(git_args)
            and previous_log.get("returncode") == 0
            and isinstance(previous_started, str)
            and isinstance(previous_completed, str)
        ):
            try:
                return _finalize_success(
                    context,
                    record,
                    operation_id=operation_id,
                    session_id=session_id,
                    git_args=git_args,
                    pending_path=pending_path,
                    receipt_path=receipt_path,
                    log_path=log_path,
                    started_at=previous_started,
                    completed_at=previous_completed,
                )
            except (HookDispatcherError, OSError, ValueError) as exc:
                return _report_receipt_failure(log_path, exc)

    pending_path.unlink(missing_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    git_trace_path = log_path.with_name(f"{operation_id}.git-trace.jsonl")
    inherited_trace = os.environ.get("GIT_TRACE2_EVENT", "").strip()
    git_trace_ref = inherited_trace or str(git_trace_path)
    _write_log(
        log_path,
        operation_id=operation_id,
        git_args=git_args,
        started_at=started_at,
        completed_at=None,
        returncode=None,
        git_trace_ref=git_trace_ref,
    )
    environment = clean_git_local_environment(context.repo_root, os.environ)
    if not inherited_trace:
        environment["GIT_TRACE2_EVENT"] = str(git_trace_path)
    dry_run = "--dry-run" in git_args or "-n" in git_args
    if not dry_run:
        environment["AGENT_RUNTIME_PUSH_OPERATION_ID"] = operation_id
        environment["AGENT_RUNTIME_SESSION_ID"] = session_id
        environment["AGENT_RUNTIME_PUSH_ARGV_JSON"] = json.dumps(
            git_args,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    result = subprocess.run(
        ["git", "push", *git_args],
        cwd=context.cwd,
        env=environment,
        check=False,
    )
    completed_at = datetime.now(timezone.utc).isoformat()
    if not inherited_trace and git_trace_path.is_file():
        git_trace_path.chmod(0o600)
    _write_log(
        log_path,
        operation_id=operation_id,
        git_args=git_args,
        started_at=started_at,
        completed_at=completed_at,
        returncode=result.returncode,
        git_trace_ref=git_trace_ref,
    )
    if result.returncode != 0:
        pending_path.unlink(missing_ok=True)
        return result.returncode
    if dry_run:
        pending_path.unlink(missing_ok=True)
        return 0
    if not pending_path.is_file():
        return 0
    try:
        return _finalize_success(
            context,
            record,
            operation_id=operation_id,
            session_id=session_id,
            git_args=git_args,
            pending_path=pending_path,
            receipt_path=receipt_path,
            log_path=log_path,
            started_at=started_at,
            completed_at=completed_at,
        )
    except (HookDispatcherError, OSError, ValueError) as exc:
        return _report_receipt_failure(log_path, exc)


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    repo = Path.cwd()
    state_root = _default_state_root()
    index = 0
    while index < len(raw_argv) and raw_argv[index] in {"--repo", "--state-root"}:
        option = raw_argv[index]
        if index + 1 >= len(raw_argv):
            print(f"ERROR: {option} requires a path", file=sys.stderr)
            return 2
        value = Path(raw_argv[index + 1])
        if option == "--repo":
            repo = value
        else:
            state_root = value
        index += 2
    try:
        context = resolve_git_context(repo)
        return push(context, state_root=state_root, argv=raw_argv[index:])
    except (HookDispatcherError, GitContextError, OSError, ValueError) as exc:
        message = exc.message if isinstance(exc, GitContextError) else str(exc)
        print(f"ERROR: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
