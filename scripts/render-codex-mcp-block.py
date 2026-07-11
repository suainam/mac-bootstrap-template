#!/usr/bin/env python3
"""Compatibility CLI for rendering the managed Codex MCP block."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from agent_mcp_runtime import (
    RuntimeInputs,
    apply_default_policy,
    desired_servers,
    load_mcp_policy,
    render_codex_toml,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context7-command", required=True)
    parser.add_argument("--context7-api-key")
    parser.add_argument("--devspace-url")
    parser.add_argument("--policy")
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
    )
    desired = desired_servers(inputs)
    policy_path = Path(args.policy) if args.policy else bootstrap / "agent/mcp-policy.json"
    desired = apply_default_policy(desired, load_mcp_policy(policy_path))
    print(render_codex_toml(desired), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
