#!/usr/bin/env python3
"""Managed stdio bridge to the official MemOS MCP server.

Resolves the project identity from the checkout OMP starts the MCP process in
and injects it as MEMOS_USER_ID, so each project gets its own MemOS memory
partition. The official @memtensor/memos-api-mcp package reads that single env
var at startup and has no per-call user_id field, so the bridge must set it
before spawning the server.

Identity resolution order (mirrors ai-memory scope):
  1. $MEMOS_USER_ID — explicit override.
  2. .ai-memory.toml `project` above cwd.
  3. git remote -> `owner-repo`.
  4. cwd basename.

API key comes from $MEMOS_API_KEY or the private ~/.omp/agent/.env (0600).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PRIVATE_ENV = Path("~/.omp/agent/.env").expanduser()
MARKER = ".ai-memory.toml"
CHANNEL = "GITHUB"


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


def marker_values(path: Path) -> dict[str, str]:
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


def resolve_user_id(cwd: Path) -> str:
    explicit = os.environ.get("MEMOS_USER_ID")
    if explicit and explicit.strip():
        return explicit.strip()
    marker = find_marker(cwd)
    if marker is not None:
        project = marker_values(marker).get("project")
        if project:
            return project
    remote = git_remote(cwd)
    derived = normalize_remote(remote) if remote else None
    if derived:
        return derived
    name = cwd.name.strip()
    return name or "default"


def resolve_api_key() -> str | None:
    return os.environ.get("MEMOS_API_KEY") or private_env_value("MEMOS_API_KEY")


def main() -> int:
    if sys.argv[1:] == ["--validate-private-config"]:
        if not resolve_api_key():
            print("MemOS private API key missing", file=sys.stderr)
            return 2
        return 0

    key = resolve_api_key()
    if not key:
        print("MemOS bridge: no API key; set MEMOS_API_KEY or private ~/.omp/agent/.env", file=sys.stderr)
        return 2

    cwd = Path.cwd().resolve()
    user_id = resolve_user_id(cwd)

    environment = os.environ.copy()
    environment["MEMOS_API_KEY"] = key
    environment["MEMOS_USER_ID"] = user_id
    environment["MEMOS_CHANNEL"] = CHANNEL

    installed = shutil.which("memos-api-mcp")
    if installed:
        os.execvpe(installed, [installed, *sys.argv[1:]], environment)
    os.execvpe("npx", ["npx", "-y", "@memtensor/memos-api-mcp@1.1.2", *sys.argv[1:]], environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
