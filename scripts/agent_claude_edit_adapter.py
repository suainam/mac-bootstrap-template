#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Mapping, Sequence

from agent_git_context import GitContextError, resolve_git_context


MAX_INPUT_BYTES = 65536
MAX_FEEDBACK_BYTES = 4096
SOURCE_ADAPTER = "claude-code-post-tool-use-v1"


class AdapterError(ValueError):
    pass


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(f"{field} must be a non-empty string")
    return value.strip()


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise AdapterError("Claude hook JSON is required on stdin")
    if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
        raise AdapterError(f"Claude hook JSON exceeds {MAX_INPUT_BYTES} bytes")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"invalid Claude hook JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise AdapterError("Claude hook payload must be a JSON object")
    return payload


def _event_id(session_id: str, tool_use_id: str, target: Path) -> str:
    material = f"{session_id}\0{tool_use_id}\0{target}".encode("utf-8")
    return "claude-edit-" + hashlib.sha256(material).hexdigest()[:24]


def claude_payload_to_event(payload: Mapping[str, Any]) -> dict[str, object]:
    event_name = _require_string(payload.get("hook_event_name"), "hook_event_name")
    if event_name != "PostToolUse":
        raise AdapterError(f"expected PostToolUse, got {event_name}")

    tool_name = _require_string(payload.get("tool_name"), "tool_name")
    if tool_name not in {"Edit", "Write"}:
        raise AdapterError(f"expected Edit or Write, got {tool_name}")

    session_id = _require_string(payload.get("session_id"), "session_id")
    tool_use_id = _require_string(payload.get("tool_use_id"), "tool_use_id")
    cwd = Path(_require_string(payload.get("cwd"), "cwd")).expanduser().resolve()
    if not cwd.is_dir():
        raise AdapterError(f"cwd is not a directory: {cwd}")

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise AdapterError("tool_input must be a JSON object")
    raw_path = _require_string(tool_input.get("file_path"), "tool_input.file_path")
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        target = cwd / target
    target = target.resolve()

    try:
        context = resolve_git_context(cwd)
    except GitContextError as exc:
        raise AdapterError(f"{exc.code}: {exc.message}") from exc
    if context.repo_root is None or not target.is_relative_to(context.repo_root):
        raise AdapterError(f"target path is outside repository: {target}")

    metadata = {
        "host_event": event_name,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "permission_mode": payload.get("permission_mode"),
    }
    return {
        "schema_version": 1,
        "event_type": "after.edit",
        "event_id": _event_id(session_id, tool_use_id, target),
        "source_adapter": SOURCE_ADAPTER,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cwd": str(cwd),
        "target_paths": [str(target)],
        "session_id": session_id,
        "metadata": metadata,
    }


def _runtime_path() -> Path:
    return Path(__file__).resolve().with_name("agent_runtime.py")


def _diagnostic_reason(stderr: str, returncode: int) -> str:
    text = stderr.strip()
    diagnostics: list[Mapping[str, object]] = []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("diagnostics"), list):
        diagnostics = [
            item for item in payload["diagnostics"] if isinstance(item, dict)
        ][:5]

    if diagnostics:
        lines: list[str] = []
        for item in diagnostics:
            gate_id = str(item.get("gate_id") or "runtime")
            message = " ".join(str(item.get("message") or "check failed").split())
            action = str(item.get("action") or "fix")
            log_ref = item.get("log_ref")
            line = f"[{gate_id}] {message} Action: {action}."
            if isinstance(log_ref, str) and log_ref:
                line += f" Log: {log_ref}."
            lines.append(line)
        reason = "\n".join(lines)
    else:
        detail = " ".join(text.split()) if text else "runtime produced no diagnostic"
        reason = f"[runtime] check failed with exit code {returncode}: {detail}"

    encoded = reason.encode("utf-8")
    if len(encoded) <= 3500:
        return reason
    return encoded[:3500].decode("utf-8", errors="ignore") + "…"


def _emit_claude_feedback(reason: str) -> None:
    payload = {"decision": "block", "reason": reason}
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(rendered.encode("utf-8")) > MAX_FEEDBACK_BYTES:
        payload = {
            "decision": "block",
            "reason": "Agent runtime diagnostic exceeded the output budget; inspect external runtime logs.",
        }
        rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    sys.stdout.write(rendered)


def run_hook(registry: Path) -> int:
    payload = _read_payload()
    event = claude_payload_to_event(payload)
    runtime = _runtime_path()
    if not runtime.is_file():
        _emit_claude_feedback(f"[runtime] runtime is missing: {runtime}")
        return 0

    env = os.environ.copy()
    env.pop("PYTHON", None)
    env.pop("PYTHON_BIN", None)
    result = subprocess.run(
        [
            sys.executable,
            str(runtime),
            "--registry",
            str(registry.expanduser().resolve()),
            "dispatch",
        ],
        cwd=Path(str(event["cwd"])),
        input=json.dumps(event, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if result.stdout:
        _emit_claude_feedback("[runtime] dispatch wrote unexpected stdout; inspect runtime logs.")
        return 0
    if result.returncode == 0 and not result.stderr:
        return 0
    _emit_claude_feedback(_diagnostic_reason(result.stderr, result.returncode))
    return 0


def render_settings(registry: Path, python: Path) -> dict[str, object]:
    executable = python.expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise AdapterError(f"python executable is not executable: {executable}")
    command = " ".join(
        shlex.quote(part)
        for part in (
            str(executable),
            str(Path(__file__).resolve()),
            "--registry",
            str(registry.expanduser().resolve()),
            "hook",
        )
    )
    return {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                            "timeout": 30,
                        }
                    ],
                }
            ]
        }
    }


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[1] / "agent" / "runtime" / "registry.jsonc"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-claude-edit-adapter")
    parser.add_argument("--registry", type=Path, default=default_registry_path())
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("hook")
    settings = subparsers.add_parser("settings")
    settings.add_argument("--python", type=Path, default=Path(sys.executable))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "hook":
            return run_hook(args.registry)
        print(
            json.dumps(
                render_settings(args.registry, args.python),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 0
    except AdapterError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
