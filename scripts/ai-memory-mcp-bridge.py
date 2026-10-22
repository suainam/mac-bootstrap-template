#!/usr/bin/env python3
"""Managed stdio bridge to the shared ai-memory primary.

Wraps the official `ai-memory mcp-bridge` so a session-less MCP client never
issues an unscoped project call: the server would resolve that to its
`shared_slot` project, silently writing into the wrong namespace.

Scope injection is limited to tool calls whose input schema declares both
`workspace` and `project`, is skipped when the caller already named a global or
explicit scope, and fails closed when the checkout has no resolvable identity.
Every other message (initialize, notifications, tools/list, responses) is
forwarded byte-for-byte, and line-delimited framing is preserved.

shortcut: the project-scoped tool list is static (mirrors the server's
tools/list); a new scoped tool needs an entry here, upgrade by reading the
schema from tools/list instead.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

MARKER = ".ai-memory.toml"
DEFAULT_DATA_DIR = "~/.omp/agent/ai-memory-cc15"
# The shared primary lives on a private address, so the endpoint is NOT baked in
# here: this file is part of the public template. Resolution order is
# $AI_MEMORY_SERVER_URL, then the 0600 env file that the private overlay owns,
# and finally a hard failure -- an unreachable default would silently point the
# bridge at a local server instead of the shared primary.
DEFAULT_PROXY = "http://127.0.0.1:7897"
PRIVATE_ENV = Path("~/.omp/agent/.env").expanduser()


def private_env_value(key: str) -> str | None:
    try:
        text = PRIVATE_ENV.read_text(errors="ignore")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :]
        if not line.startswith(f"{key}="):
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value or None
    return None


def resolve_server_url() -> str:
    for candidate in (os.environ.get("AI_MEMORY_SERVER_URL"), private_env_value("AI_MEMORY_SERVER_URL")):
        if candidate and candidate.strip():
            return candidate.strip()
    raise SystemExit(
        "ai-memory bridge: no server URL configured; set AI_MEMORY_SERVER_URL "
        "or add it to the private ~/.omp/agent/.env (see docs/ai-memory-shared-primary.md)"
    )


# Tools whose input schema declares both `workspace` and `project`.
PROJECT_SCOPED_TOOLS = frozenset(
    {
        "memory_auto_improve",
        "memory_briefing",
        "memory_delete_page",
        "memory_explore",
        "memory_feedback",
        "memory_forget_sweep",
        "memory_handoff_accept",
        "memory_handoff_begin",
        "memory_handoff_cancel",
        "memory_handoff_list",
        "memory_lint",
        "memory_message_cancel",
        "memory_message_list",
        "memory_message_pop",
        "memory_query",
        "memory_read_page",
        "memory_read_session_observations",
        "memory_recent",
        "memory_restore_page",
        "memory_status",
        "memory_write_page",
    }
)


def marker_values(path: Path) -> dict[str, str]:
    """Read top-level `key = "value"` pairs; section bodies are irrelevant here."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            break
        key, sep, raw = stripped.partition("=")
        if not sep or key.strip() in values:
            continue
        value = raw.strip().strip("\"'")
        if value:
            values[key.strip()] = value
    return values


def find_marker(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        candidate = directory / MARKER
        if candidate.is_file():
            return candidate
    return None


def normalize_remote(url: str) -> str | None:
    """`git@host:owner/repo.git` / `https://host/owner/repo` -> `owner-repo`."""
    value = url.strip()
    if not value:
        return None
    match = re.match(r"^[^/@]+@([^:/]+):(.+)$", value)
    if match:
        path = match.group(2)
    else:
        path = re.sub(r"^[a-z+]+://[^/]+/", "", value)
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return None
    return "-".join(segments).lower()


def git_remote(cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def resolve_scope(cwd: Path) -> tuple[str, str] | None:
    """Explicit marker values win; otherwise derive from the origin remote."""
    workspace = project = None
    marker = find_marker(cwd)
    if marker is not None:
        values = marker_values(marker)
        workspace = values.get("workspace") or None
        project = values.get("project") or None
    if workspace and project:
        return workspace, project
    remote = git_remote(cwd)
    derived = normalize_remote(remote) if remote else None
    if not derived:
        return None
    return workspace or "default", project or derived


def is_explicitly_scoped(arguments: dict) -> bool:
    if arguments.get("global") is True:
        return True
    scopes = arguments.get("scopes")
    return isinstance(scopes, list) and bool(scopes)


def scoped_arguments(name: str, arguments: dict, scope: tuple[str, str] | None) -> dict | None:
    """Return the arguments to send, or None when the call must fail closed."""
    if name not in PROJECT_SCOPED_TOOLS or is_explicitly_scoped(arguments):
        return arguments
    missing = [key for key in ("workspace", "project") if not arguments.get(key)]
    if not missing:
        return arguments
    if scope is None:
        return None
    injected = dict(arguments)
    for key in missing:
        injected[key] = scope[0] if key == "workspace" else scope[1]
    return injected


def rewrite(line: bytes, scope: tuple[str, str] | None) -> tuple[bytes, dict | None]:
    """Rewrite one client line; also return an MCP error when the call fails closed."""
    try:
        message = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return line, None
    if not isinstance(message, dict) or message.get("method") != "tools/call":
        return line, None
    params = message.get("params")
    if not isinstance(params, dict):
        return line, None
    name = params.get("name")
    arguments = params.get("arguments")
    if not isinstance(name, str):
        return line, None
    if not isinstance(arguments, dict):
        arguments = {}
    resolved = scoped_arguments(name, arguments, scope)
    if resolved is None:
        error = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32602,
                "message": (
                    f"ai-memory bridge: refusing unscoped {name}; "
                    f"no {MARKER} workspace/project and no git origin to derive one"
                ),
            },
        }
        return b"", error
    if resolved is arguments:
        return line, None
    message["params"] = {**params, "arguments": resolved}
    return (json.dumps(message) + "\n").encode(), None


def child_command(bridge_bin: str, data_dir: str, server_url: str) -> list[str]:
    return [bridge_bin, "mcp-bridge", "--no-session-id", "--data-dir", data_dir, "--server-url", server_url]


def prepare_environment(data_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    if not env.get("HTTP_PROXY") and not env.get("http_proxy"):
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env[key] = DEFAULT_PROXY
    if not env.get("NO_PROXY") and not env.get("no_proxy"):
        env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1,::1"
    token_file = data_dir / "auth-token"
    if token_file.is_file():
        bearer = token_file.read_text(errors="ignore").strip()
        if bearer:
            env["AI_MEMORY_AUTH_TOKEN"] = bearer
    env["AI_MEMORY_DATA_DIR"] = str(data_dir)
    return env


def parse_args(argv: list[str]) -> dict[str, str]:
    options = {
        "data-dir": os.environ.get("AI_MEMORY_DATA_DIR", DEFAULT_DATA_DIR),
        "server-url": os.environ.get("AI_MEMORY_SERVER_URL") or private_env_value("AI_MEMORY_SERVER_URL"),
        "bridge-bin": os.environ.get("AI_MEMORY_BRIDGE_BIN", "ai-memory"),
        "scope-cwd": os.environ.get("AI_MEMORY_SCOPE_CWD", os.getcwd()),
    }
    index = 0
    while index < len(argv):
        flag = argv[index]
        if flag in ("-h", "--help"):
            print(__doc__)
            raise SystemExit(0)
        key = flag[2:] if flag.startswith("--") else ""
        if key not in options or index + 1 >= len(argv):
            print(f"unknown or incomplete option: {flag}", file=sys.stderr)
            raise SystemExit(2)
        options[key] = argv[index + 1]
        index += 2
    return options


def pump(child_stdout) -> None:
    for line in iter(child_stdout.readline, b""):
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
    child_stdout.close()


def main(argv: list[str]) -> int:
    options = parse_args(argv)
    bridge_bin = shutil.which(options["bridge-bin"])
    if not bridge_bin:
        print(f"ai-memory bridge: cannot find {options['bridge-bin']} on PATH", file=sys.stderr)
        return 2
    data_dir = Path(options["data-dir"]).expanduser()
    scope = resolve_scope(Path(options["scope-cwd"]).expanduser())
    if scope is None:
        print(
            f"ai-memory bridge: no scope resolved from {options['scope-cwd']}; "
            "project-scoped calls will be refused",
            file=sys.stderr,
        )
    child = subprocess.Popen(
        child_command(bridge_bin, str(data_dir), options["server-url"]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=prepare_environment(data_dir),
    )
    assert child.stdin is not None and child.stdout is not None
    threading.Thread(target=pump, args=(child.stdout,), daemon=True).start()
    for line in iter(sys.stdin.buffer.readline, b""):
        forwarded, error = rewrite(line, scope)
        if error is not None:
            sys.stdout.buffer.write((json.dumps(error) + "\n").encode())
            sys.stdout.buffer.flush()
            continue
        if forwarded:
            child.stdin.write(forwarded)
            child.stdin.flush()
    child.stdin.close()
    return child.wait()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
