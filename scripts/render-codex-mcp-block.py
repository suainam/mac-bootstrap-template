#!/usr/bin/env python3
"""Compatibility CLI for rendering the managed Codex MCP block."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from agent_mcp_runtime import RuntimeInputs, desired_servers, render_codex_toml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context7-command", required=True)
    parser.add_argument("--context7-api-key")
    parser.add_argument("--devspace-url")
    parser.add_argument("--enable-x-api", action="store_true")
    parser.add_argument("--x-api-command", default="x-mcp-bridge.sh")
    args = parser.parse_args()

    bootstrap = Path(__file__).resolve().parents[1]
    inputs = RuntimeInputs.from_env(
        bootstrap=bootstrap,
        context7_command=args.context7_command,
    )
    inputs = replace(
        inputs,
        context7_key=args.context7_api_key or inputs.context7_key,
        devspace_enabled=bool(args.devspace_url),
        devspace_url=args.devspace_url or "",
        xapi_enabled=args.enable_x_api,
        xapi_command=args.x_api_command if args.enable_x_api else "",
    )
    print(render_codex_toml(desired_servers(inputs)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
