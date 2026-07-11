#!/usr/bin/env python3
"""Launch Codex with an MCP profile from the mac-bootstrap policy."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from agent_mcp_runtime import load_mcp_policy


def build_command(policy_path: Path, profile: str, codex_args: list[str]) -> list[str]:
    policy = load_mcp_policy(policy_path)
    profiles = policy["profiles"]
    if profile not in profiles:
        raise ValueError(f"unknown MCP profile: {profile}")
    overrides = [
        item
        for name in profiles[profile]
        for item in ("-c", f"mcp_servers.{name}.enabled=true")
    ]
    return ["codex", *overrides, *codex_args]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile")
    parser.add_argument("--print-command", action="store_true")
    parser.add_argument("codex_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    bootstrap = Path(__file__).resolve().parents[1]
    command = build_command(
        bootstrap / "agent/mcp-policy.json", args.profile, args.codex_args
    )
    if args.print_command:
        print(json.dumps(command))
        return 0
    os.execvp(command[0], command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
