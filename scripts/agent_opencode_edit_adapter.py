#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

from agent_git_context import GitContextError, resolve_git_context


MAX_INPUT_BYTES = 65536
MAX_FEEDBACK_BYTES = 4096
SOURCE_ADAPTER = "opencode-tool-execute-after-v1"
SUPPORTED_TOOLS = {"write", "edit", "apply_patch"}
PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update) File: (.+)$", re.MULTILINE)


class AdapterError(ValueError):
    pass


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(f"{field} must be a non-empty string")
    return value.strip()


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise AdapterError("OpenCode hook JSON is required on stdin")
    if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
        raise AdapterError(f"OpenCode hook JSON exceeds {MAX_INPUT_BYTES} bytes")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"invalid OpenCode hook JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise AdapterError("OpenCode hook payload must be a JSON object")
    return payload


def _event_id(session_id: str, call_id: str, target: Path) -> str:
    material = f"{session_id}\0{call_id}\0{target}".encode("utf-8")
    return "opencode-edit-" + hashlib.sha256(material).hexdigest()[:24]


def _patch_target(args: Mapping[str, Any]) -> str:
    patch_text = _require_string(args.get("patchText"), "input.args.patchText")
    paths = tuple(dict.fromkeys(match.strip() for match in PATCH_PATH.findall(patch_text)))
    if len(paths) != 1:
        raise AdapterError("apply_patch must contain exactly one target file")
    return paths[0]


def _target_path(tool: str, args: Mapping[str, Any]) -> str:
    if tool == "apply_patch":
        return _patch_target(args)
    return _require_string(args.get("filePath"), "input.args.filePath")


def opencode_payload_to_event(payload: Mapping[str, Any]) -> dict[str, object]:
    hook_input = payload.get("input")
    if not isinstance(hook_input, dict):
        raise AdapterError("input must be a JSON object")
    hook_output = payload.get("output")
    if not isinstance(hook_output, dict):
        raise AdapterError("output must be a JSON object")

    tool = _require_string(hook_input.get("tool"), "input.tool")
    if tool not in SUPPORTED_TOOLS:
        raise AdapterError(f"expected write, edit, or apply_patch, got {tool}")
    session_id = _require_string(hook_input.get("sessionID"), "input.sessionID")
    call_id = _require_string(hook_input.get("callID"), "input.callID")
    args = hook_input.get("args")
    if not isinstance(args, dict):
        raise AdapterError("input.args must be a JSON object")

    cwd = Path(_require_string(payload.get("directory"), "directory")).expanduser().resolve()
    if not cwd.is_dir():
        raise AdapterError(f"directory is not a directory: {cwd}")
    raw_path = _target_path(tool, args)
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
        "host_event": "tool.execute.after",
        "tool_name": tool,
        "call_id": call_id,
        "output_title": hook_output.get("title"),
    }
    return {
        "schema_version": 1,
        "event_type": "after.edit",
        "event_id": _event_id(session_id, call_id, target),
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


def _emit_feedback(reason: str) -> None:
    payload = {"additionalContext": reason}
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(rendered.encode("utf-8")) > MAX_FEEDBACK_BYTES:
        payload = {
            "additionalContext": (
                "Agent runtime diagnostic exceeded the output budget; "
                "inspect external runtime logs."
            )
        }
        rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    sys.stdout.write(rendered)


def run_hook(registry: Path) -> int:
    payload = _read_payload()
    event = opencode_payload_to_event(payload)
    runtime = _runtime_path()
    if not runtime.is_file():
        _emit_feedback(f"[runtime] runtime is missing: {runtime}")
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
        _emit_feedback("[runtime] dispatch wrote unexpected stdout; inspect runtime logs.")
        return 0
    if result.returncode == 0 and not result.stderr:
        return 0
    _emit_feedback(_diagnostic_reason(result.stderr, result.returncode))
    return 0


def render_plugin(registry: Path, python: Path) -> str:
    executable = python.expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise AdapterError(f"python executable is not executable: {executable}")
    command = [
        str(executable),
        str(Path(__file__).resolve()),
        "--registry",
        str(registry.expanduser().resolve()),
        "hook",
    ]
    command_json = json.dumps(command, ensure_ascii=False)
    tools_json = json.dumps(sorted(SUPPORTED_TOOLS))
    return f'''export const AgentRuntimeEditPlugin = async ({{ directory, worktree }}) => ({{
  "tool.execute.after": async (input, output) => {{
    if (!{tools_json}.includes(input.tool)) return;
    const process = Bun.spawn({command_json}, {{
      cwd: directory,
      stdin: "pipe",
      stdout: "pipe",
      stderr: "pipe",
    }});
    process.stdin.write(JSON.stringify({{ input, output, directory, worktree }}));
    process.stdin.end();
    const [stdout, stderr, exitCode] = await Promise.all([
      new Response(process.stdout).text(),
      new Response(process.stderr).text(),
      process.exited,
    ]);
    if (exitCode !== 0) {{
      const detail = stderr.trim() || `adapter exited with code ${{exitCode}}`;
      output.output = `[agent-runtime] ${{detail}}\n${{output.output}}`;
      return;
    }}
    if (!stdout.trim()) return;
    let feedback;
    try {{
      feedback = JSON.parse(stdout);
    }} catch {{
      output.output = `[agent-runtime] invalid adapter output\n${{output.output}}`;
      return;
    }}
    if (typeof feedback.additionalContext === "string" && feedback.additionalContext) {{
      output.output = `${{feedback.additionalContext}}\n${{output.output}}`;
    }}
  }},
}});
'''


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[1] / "agent" / "runtime" / "registry.jsonc"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-opencode-edit-adapter")
    parser.add_argument("--registry", type=Path, default=default_registry_path())
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("hook")
    plugin = subparsers.add_parser("plugin")
    plugin.add_argument("--python", type=Path, default=Path(sys.executable))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "hook":
            return run_hook(args.registry)
        sys.stdout.write(render_plugin(args.registry, args.python))
        return 0
    except AdapterError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
