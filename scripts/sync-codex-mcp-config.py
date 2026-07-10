#!/usr/bin/env python3
"""Rewrite managed MCP stanzas in Codex config.toml idempotently."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import tempfile

from agent_mcp_runtime import managed_server_names, retired_server_names


START_MARKER = "# BEGIN MAC-BOOTSTRAP MANAGED MCPS"
END_MARKER = "# END MAC-BOOTSTRAP MANAGED MCPS"
MANAGED_PREFIXES = tuple(
    f"mcp_servers.{name}" for name in managed_server_names() + retired_server_names()
)


def strip_managed_sections(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    skip_table = False
    inside_marker = False

    for line in lines:
        stripped = line.strip()
        if stripped == START_MARKER:
            inside_marker = True
            skip_table = False
            continue
        if stripped == END_MARKER:
            inside_marker = False
            continue
        if inside_marker:
            continue

        if stripped.startswith("[") and stripped.endswith("]"):
            header = stripped[1:-1].strip()
            skip_table = any(
                header == prefix or header.startswith(prefix + ".")
                for prefix in MANAGED_PREFIXES
            )
            if skip_table:
                continue

        if skip_table:
            continue

        out.append(line)

    while out and not out[-1].strip():
        out.pop()

    return "\n".join(out)


def build_output(existing_text: str, managed_block: str) -> str:
    stripped = strip_managed_sections(existing_text)
    block = managed_block.strip("\n")
    if stripped:
        return f"{stripped}\n\n{block}\n"
    return f"{block}\n"


def write_output(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.chmod(mode)
        temp_path.replace(path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config_path")
    parser.add_argument("managed_block_path")
    args = parser.parse_args()

    config_path = Path(args.config_path).expanduser()
    managed_block_path = Path(args.managed_block_path)

    existing_text = config_path.read_text() if config_path.exists() else ""
    managed_block = managed_block_path.read_text()
    write_output(config_path, build_output(existing_text, managed_block))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
