"""Codex MCP profile launcher tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "scripts/agent_mcp_runtime.py"
RUNTIME_SPEC = importlib.util.spec_from_file_location("agent_mcp_runtime", RUNTIME_PATH)
assert RUNTIME_SPEC and RUNTIME_SPEC.loader
runtime = importlib.util.module_from_spec(RUNTIME_SPEC)
sys.modules[RUNTIME_SPEC.name] = runtime
RUNTIME_SPEC.loader.exec_module(runtime)

SCRIPT_PATH = ROOT / "scripts/codex-mcp-profile.py"
SPEC = importlib.util.spec_from_file_location("codex_mcp_profile", SCRIPT_PATH)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_build_command_enables_profile_servers(tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "version": 1,
                "default_enabled": {"context7": False, "devspace": False},
                "profiles": {"docs": ["context7"]},
            }
        )
    )
    assert launcher.build_command(policy, "docs", ["-C", "/repo"]) == [
        "codex",
        "-c",
        "mcp_servers.context7.enabled=true",
        "-C",
        "/repo",
    ]
