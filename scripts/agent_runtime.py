#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


EVENT_SCHEMA_VERSION = 1
REGISTRY_SCHEMA_VERSION = 1
MAX_DIAGNOSTICS = 5
MAX_DIAGNOSTIC_BYTES = 4096
MAX_EVENT_BYTES = 65536
MAX_METADATA_BYTES = 32768
MAX_TARGET_PATHS = 256
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 300.0


class EventError(ValueError):
    pass


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class StandardEvent:
    schema_version: int
    event_type: str
    event_id: str
    source_adapter: str
    timestamp: str
    cwd: Path
    target_paths: tuple[str, ...]
    session_id: str
    metadata: Mapping[str, Any]

    def environment(self) -> dict[str, str]:
        payload = {
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "event_id": self.event_id,
            "source_adapter": self.source_adapter,
            "timestamp": self.timestamp,
            "cwd": str(self.cwd),
            "target_paths": list(self.target_paths),
            "session_id": self.session_id,
            "metadata": dict(self.metadata),
        }
        return {
            "AGENT_RUNTIME_EVENT_TYPE": self.event_type,
            "AGENT_RUNTIME_EVENT_ID": self.event_id,
            "AGENT_RUNTIME_SOURCE_ADAPTER": self.source_adapter,
            "AGENT_RUNTIME_SESSION_ID": self.session_id,
            "AGENT_RUNTIME_EVENT_JSON": json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        }


@dataclass(frozen=True)
class RepositoryState:
    repo_root: Path | None
    enabled: bool
    profile: str | None


@dataclass(frozen=True)
class GateSpec:
    gate_id: str
    events: tuple[str, ...]
    path_globs: tuple[str, ...]
    command: tuple[str, ...]
    cwd: str
    mode: str
    timeout_seconds: float
    failure_policy: str
    output_policy: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeRegistry:
    path: Path
    profiles: Mapping[str, tuple[str, ...]]
    gates: Mapping[str, GateSpec]
    diagnostic_limit: int
    diagnostic_bytes: int
    log_dir: Path


def strip_jsonc(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            while index < len(text) and text[index] != "\n":
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventError(f"{field} must be a non-empty string")
    return value


def _read_event(stream: str) -> dict[str, Any]:
    if not stream.strip():
        raise EventError("standard event JSON is required on stdin")
    if len(stream.encode("utf-8")) > MAX_EVENT_BYTES:
        raise EventError(f"standard event exceeds {MAX_EVENT_BYTES} bytes")
    try:
        payload = json.loads(stream)
    except json.JSONDecodeError as exc:
        raise EventError(f"invalid standard event JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise EventError("standard event must be a JSON object")
    return payload


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _resolve_repo_root(cwd: Path) -> Path | None:
    result = _git(cwd, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _git_config(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _git(repo_root, "config", "--local", *args)


def resolve_repository_state(cwd: Path) -> RepositoryState:
    repo_root = _resolve_repo_root(cwd)
    if repo_root is None:
        return RepositoryState(repo_root=None, enabled=False, profile=None)

    enabled_result = _git_config(repo_root, "--bool", "--get", "agent.runtime.enabled")
    if enabled_result.returncode == 1:
        return RepositoryState(repo_root=repo_root, enabled=False, profile=None)
    if enabled_result.returncode != 0:
        detail = enabled_result.stderr.strip() or "invalid agent.runtime.enabled"
        raise ConfigurationError(detail)
    enabled_value = enabled_result.stdout.strip().lower()
    if enabled_value != "true":
        return RepositoryState(repo_root=repo_root, enabled=False, profile=None)

    profile_result = _git_config(repo_root, "--get", "agent.runtime.profile")
    if profile_result.returncode != 0 or not profile_result.stdout.strip():
        raise ConfigurationError(
            "agent.runtime.profile is required when agent.runtime.enabled=true"
        )
    return RepositoryState(
        repo_root=repo_root,
        enabled=True,
        profile=profile_result.stdout.strip(),
    )


def parse_standard_event(payload: Mapping[str, Any]) -> tuple[StandardEvent, RepositoryState]:
    schema_version = payload.get("schema_version")
    if schema_version != EVENT_SCHEMA_VERSION:
        raise EventError(
            f"unsupported event schema_version {schema_version!r}; expected {EVENT_SCHEMA_VERSION}"
        )
    event_type = _require_string(payload.get("event_type"), "event_type")
    event_id = _require_string(payload.get("event_id"), "event_id")
    source_adapter = _require_string(
        payload.get("source_adapter"), "source_adapter"
    )
    timestamp = _require_string(payload.get("timestamp"), "timestamp")
    session_id = _require_string(payload.get("session_id"), "session_id")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise EventError("metadata must be a JSON object")
    if len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) > MAX_METADATA_BYTES:
        raise EventError(f"metadata exceeds {MAX_METADATA_BYTES} bytes")

    raw_paths = payload.get("target_paths")
    if not isinstance(raw_paths, list) or any(not isinstance(item, str) for item in raw_paths):
        raise EventError("target_paths must be a list of strings")
    if len(raw_paths) > MAX_TARGET_PATHS:
        raise EventError(f"target_paths exceeds {MAX_TARGET_PATHS} entries")

    cwd = Path(_require_string(payload.get("cwd"), "cwd")).expanduser().resolve()
    if not cwd.is_dir():
        raise EventError(f"cwd is not a directory: {cwd}")
    state = resolve_repository_state(cwd)

    normalized_paths: list[str] = []
    if state.repo_root is None:
        normalized_paths = list(raw_paths)
    else:
        for raw_path in raw_paths:
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = cwd / candidate
            candidate = candidate.resolve()
            if not candidate.is_relative_to(state.repo_root):
                raise EventError(f"target path is outside repository: {raw_path}")
            normalized_paths.append(candidate.relative_to(state.repo_root).as_posix())

    return (
        StandardEvent(
            schema_version=EVENT_SCHEMA_VERSION,
            event_type=event_type,
            event_id=event_id,
            source_adapter=source_adapter,
            timestamp=timestamp,
            cwd=cwd,
            target_paths=tuple(normalized_paths),
            session_id=session_id,
            metadata=metadata,
        ),
        state,
    )


def _require_string_list(value: object, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ConfigurationError(f"{field} must be a list of non-empty strings")
    if not allow_empty and not value:
        raise ConfigurationError(f"{field} must not be empty")
    return tuple(value)


def _runtime_number(
    runtime: Mapping[str, Any], key: str, default: int, maximum: int
) -> int:
    value = runtime.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigurationError(f"runtime.{key} must be a positive integer")
    return min(value, maximum)


def _parse_gate(gate_id: str, config: object) -> GateSpec:
    if not isinstance(config, dict):
        raise ConfigurationError(f"gate {gate_id} must be an object")
    command = config.get("command")
    if not isinstance(command, list) or not command or any(
        not isinstance(item, str) or not item or "\x00" in item for item in command
    ):
        raise ConfigurationError(
            f"gate {gate_id} command must be a non-empty argv list"
        )
    executable = Path(command[0]).expanduser()
    if not executable.is_absolute():
        raise ConfigurationError(
            f"gate {gate_id} command executable must be an absolute path"
        )

    cwd = config.get("cwd", "repo")
    if cwd not in {"repo", "event"}:
        raise ConfigurationError(f"gate {gate_id} cwd must be repo or event")
    mode = config.get("mode", "sync")
    if mode not in {"sync", "async"}:
        raise ConfigurationError(f"gate {gate_id} mode must be sync or async")
    timeout = config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or timeout <= 0
        or timeout > MAX_TIMEOUT_SECONDS
    ):
        raise ConfigurationError(
            f"gate {gate_id} timeout_seconds must be between 0 and {MAX_TIMEOUT_SECONDS}"
        )
    failure_policy = config.get("failure_policy", "block")
    if failure_policy not in {"block", "diagnose"}:
        raise ConfigurationError(
            f"gate {gate_id} failure_policy must be block or diagnose"
        )
    if mode == "async" and failure_policy == "block":
        raise ConfigurationError(
            f"gate {gate_id} async mode cannot use block failure_policy"
        )
    output_policy = config.get("output_policy", "silent")
    if output_policy not in {"silent", "diagnostic"}:
        raise ConfigurationError(
            f"gate {gate_id} output_policy must be silent or diagnostic"
        )
    return GateSpec(
        gate_id=gate_id,
        events=_require_string_list(
            config.get("events"), f"gate {gate_id} events", allow_empty=False
        ),
        path_globs=_require_string_list(
            config.get("path_globs", []), f"gate {gate_id} path_globs"
        ),
        command=tuple(str(executable) if index == 0 else value for index, value in enumerate(command)),
        cwd=cwd,
        mode=mode,
        timeout_seconds=float(timeout),
        failure_policy=failure_policy,
        output_policy=output_policy,
        capabilities=_require_string_list(
            config.get("capabilities", []), f"gate {gate_id} capabilities"
        ),
    )


def load_registry(path: Path) -> RuntimeRegistry:
    try:
        raw = json.loads(strip_jsonc(path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise ConfigurationError(f"cannot read registry {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"invalid registry JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("registry must be a JSON object")
    if raw.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ConfigurationError(
            f"unsupported registry schema_version {raw.get('schema_version')!r}; "
            f"expected {REGISTRY_SCHEMA_VERSION}"
        )

    gates_raw = raw.get("gates")
    if not isinstance(gates_raw, dict):
        raise ConfigurationError("registry.gates must be an object")
    gates = {
        gate_id: _parse_gate(gate_id, config)
        for gate_id, config in gates_raw.items()
        if isinstance(gate_id, str) and gate_id
    }
    if len(gates) != len(gates_raw):
        raise ConfigurationError("registry gate IDs must be non-empty strings")

    profiles_raw = raw.get("profiles")
    if not isinstance(profiles_raw, dict):
        raise ConfigurationError("registry.profiles must be an object")
    profiles: dict[str, tuple[str, ...]] = {}
    for profile_id, config in profiles_raw.items():
        if not isinstance(profile_id, str) or not profile_id or not isinstance(config, dict):
            raise ConfigurationError("registry profiles must use non-empty string IDs")
        gate_ids = _require_string_list(
            config.get("gates", []), f"profile {profile_id} gates"
        )
        unknown = [gate_id for gate_id in gate_ids if gate_id not in gates]
        if unknown:
            raise ConfigurationError(
                f"profile {profile_id} references unknown gate: {unknown[0]}"
            )
        if len(set(gate_ids)) != len(gate_ids):
            raise ConfigurationError(f"profile {profile_id} contains duplicate gates")
        profiles[profile_id] = gate_ids

    runtime = raw.get("runtime", {})
    if not isinstance(runtime, dict):
        raise ConfigurationError("registry.runtime must be an object")
    raw_log_dir = runtime.get(
        "log_dir", "$HOME/.local/state/mac-bootstrap-agent-runtime/logs"
    )
    if not isinstance(raw_log_dir, str) or not raw_log_dir:
        raise ConfigurationError("runtime.log_dir must be a non-empty string")
    log_dir = Path(os.path.expandvars(os.path.expanduser(raw_log_dir)))
    if not log_dir.is_absolute():
        raise ConfigurationError("runtime.log_dir must resolve to an absolute path")

    return RuntimeRegistry(
        path=path.resolve(),
        profiles=profiles,
        gates=gates,
        diagnostic_limit=_runtime_number(
            runtime, "diagnostic_limit", MAX_DIAGNOSTICS, MAX_DIAGNOSTICS
        ),
        diagnostic_bytes=_runtime_number(
            runtime,
            "diagnostic_bytes",
            MAX_DIAGNOSTIC_BYTES,
            MAX_DIAGNOSTIC_BYTES,
        ),
        log_dir=log_dir,
    )


def _path_matches(path: str, patterns: Sequence[str]) -> bool:
    name = Path(path).name
    return any(
        fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(name, pattern)
        for pattern in patterns
    )


def build_plan(
    event: StandardEvent,
    state: RepositoryState,
    registry: RuntimeRegistry,
) -> dict[str, Any]:
    if not state.enabled:
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "enabled": False,
            "repo_root": str(state.repo_root) if state.repo_root else None,
            "profile": None,
            "matched_gates": [],
            "matched_gate_details": [],
            "skipped_gates": [],
        }
    assert state.profile is not None
    if state.profile not in registry.profiles:
        raise ConfigurationError(f"unknown profile: {state.profile}")

    matched: list[str] = []
    matched_details: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for gate_id in registry.profiles[state.profile]:
        gate = registry.gates[gate_id]
        if event.event_type not in gate.events:
            skipped.append({"gate_id": gate_id, "reason": "event-type"})
            continue
        if gate.path_globs and not any(
            _path_matches(path, gate.path_globs) for path in event.target_paths
        ):
            skipped.append({"gate_id": gate_id, "reason": "path-glob"})
            continue
        matched.append(gate_id)
        matched_details.append(
            {
                "gate_id": gate_id,
                "mode": gate.mode,
                "timeout_seconds": gate.timeout_seconds,
                "failure_policy": gate.failure_policy,
                "output_policy": gate.output_policy,
                "capabilities": list(gate.capabilities),
            }
        )
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "enabled": True,
        "repo_root": str(state.repo_root),
        "profile": state.profile,
        "matched_gates": matched,
        "matched_gate_details": matched_details,
        "skipped_gates": skipped,
    }


def _sanitize_filename(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return sanitized or "event"


def _diagnostic(gate_id: str, message: str) -> dict[str, str]:
    return {"gate_id": gate_id, "message": " ".join(message.split())[:1024]}


def emit_diagnostics(
    status: str,
    diagnostics: Sequence[Mapping[str, str]],
    *,
    count_limit: int,
    byte_limit: int,
) -> None:
    payload = {
        "status": status,
        "diagnostics": list(diagnostics[:count_limit]),
    }
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(rendered.encode("utf-8")) > byte_limit:
        payload = {
            "status": status,
            "diagnostics": [
                {"gate_id": "runtime", "message": "diagnostic output truncated"}
            ],
        }
        rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    sys.stderr.write(rendered)


def _gate_cwd(gate: GateSpec, event: StandardEvent, state: RepositoryState) -> Path:
    assert state.repo_root is not None
    cwd = state.repo_root if gate.cwd == "repo" else event.cwd
    if not cwd.resolve().is_relative_to(state.repo_root):
        raise ConfigurationError(f"gate {gate.gate_id} cwd is outside repository")
    return cwd


def _run_sync_gate(
    gate: GateSpec,
    event: StandardEvent,
    state: RepositoryState,
) -> dict[str, str] | None:
    env = os.environ.copy()
    env.update(event.environment())
    try:
        result = subprocess.run(
            list(gate.command),
            cwd=_gate_cwd(gate, event, state),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=gate.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _diagnostic(
            gate.gate_id, f"gate timed out after {gate.timeout_seconds:g}s"
        )
    except OSError as exc:
        return _diagnostic(gate.gate_id, f"gate could not start: {exc}")
    if result.returncode == 0:
        return None
    detail = ""
    if gate.output_policy == "diagnostic":
        detail = result.stderr.strip() or result.stdout.strip()
    suffix = f": {detail}" if detail else ""
    return _diagnostic(
        gate.gate_id, f"gate failed with exit code {result.returncode}{suffix}"
    )


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)


def _run_async_worker(job_path: Path) -> int:
    try:
        payload = json.loads(job_path.read_text(encoding="utf-8"))
        command = payload.get("command")
        cwd = Path(str(payload.get("cwd") or ""))
        log_path = Path(str(payload.get("log_path") or ""))
        timeout = payload.get("timeout_seconds")
        if (
            payload.get("schema_version") != 1
            or not isinstance(command, list)
            or not command
            or any(not isinstance(item, str) or not item for item in command)
            or not Path(command[0]).is_absolute()
            or not cwd.is_absolute()
            or not log_path.is_absolute()
            or not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout <= 0
            or timeout > MAX_TIMEOUT_SECONDS
        ):
            return 2
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("wb") as log_handle:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                return_code = process.wait(timeout=float(timeout))
                if return_code != 0:
                    log_handle.write(
                        f"\nERROR: gate exited with code {return_code}\n".encode()
                    )
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                log_handle.write(
                    f"ERROR: gate timed out after {float(timeout):g}s\n".encode()
                )
            except OSError as exc:
                log_handle.write(f"ERROR: gate could not start: {exc}\n".encode())
        return 0
    except (OSError, ValueError, json.JSONDecodeError):
        return 2
    finally:
        job_path.unlink(missing_ok=True)


def _launch_async_gate(
    gate: GateSpec,
    event: StandardEvent,
    state: RepositoryState,
    registry: RuntimeRegistry,
) -> dict[str, str] | None:
    env = os.environ.copy()
    env.update(event.environment())
    stem = (
        f"{_sanitize_filename(event.event_id)}-"
        f"{_sanitize_filename(gate.gate_id)}-{time.time_ns()}"
    )
    job_path = registry.log_dir / f"{stem}.job.json"
    log_path = registry.log_dir / f"{stem}.log"
    try:
        registry.log_dir.mkdir(parents=True, exist_ok=True)
        _write_private_json(
            job_path,
            {
                "schema_version": 1,
                "command": list(gate.command),
                "cwd": str(_gate_cwd(gate, event, state)),
                "timeout_seconds": gate.timeout_seconds,
                "log_path": str(log_path),
            },
        )
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_async-worker", str(job_path)],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, ConfigurationError) as exc:
        job_path.unlink(missing_ok=True)
        return _diagnostic(gate.gate_id, f"async gate could not start: {exc}")
    return None


def dispatch(
    event: StandardEvent,
    state: RepositoryState,
    registry: RuntimeRegistry,
    plan: Mapping[str, Any],
) -> int:
    diagnostics: list[dict[str, str]] = []
    blocked = False
    for gate_id in plan.get("matched_gates", []):
        gate = registry.gates[str(gate_id)]
        diagnostic = (
            _run_sync_gate(gate, event, state)
            if gate.mode == "sync"
            else _launch_async_gate(gate, event, state, registry)
        )
        if diagnostic is None:
            continue
        diagnostics.append(diagnostic)
        if gate.failure_policy == "block":
            blocked = True
            break

    if diagnostics:
        emit_diagnostics(
            "blocked" if blocked else "diagnosed",
            diagnostics,
            count_limit=registry.diagnostic_limit,
            byte_limit=registry.diagnostic_bytes,
        )
    return 1 if blocked else 0


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[1] / "agent" / "runtime" / "registry.jsonc"


def _print_json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


def doctor(registry_path: Path) -> int:
    registry = load_registry(registry_path)
    cwd = Path.cwd().resolve()
    state = resolve_repository_state(cwd)
    _print_json(
        {
            "registry_path": str(registry.path),
            "registry_schema_version": REGISTRY_SCHEMA_VERSION,
            "event_schema_version": EVENT_SCHEMA_VERSION,
            "repo_root": str(state.repo_root) if state.repo_root else None,
            "enabled": state.enabled,
            "profile": state.profile,
            "known_profiles": list(registry.profiles),
            "known_gates": list(registry.gates),
            "diagnostic_limit": registry.diagnostic_limit,
            "diagnostic_bytes": registry.diagnostic_bytes,
            "log_dir": str(registry.log_dir),
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-runtime")
    parser.add_argument("--registry", type=Path, default=default_registry_path())
    parser.add_argument("command", choices=("dispatch", "dry-run", "explain", "doctor"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] == "_async-worker":
        if len(raw_args) != 2:
            return 2
        return _run_async_worker(Path(raw_args[1]))

    args = build_parser().parse_args(raw_args)
    try:
        if args.command == "doctor":
            return doctor(args.registry)

        payload = _read_event(sys.stdin.read())
        event, state = parse_standard_event(payload)
        if args.command == "dispatch" and not state.enabled:
            return 0

        registry = load_registry(args.registry)
        plan = build_plan(event, state, registry)
        if args.command in {"dry-run", "explain"}:
            result = dict(plan)
            result["command"] = args.command
            _print_json(result)
            return 0
        return dispatch(event, state, registry, plan)
    except EventError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ConfigurationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
