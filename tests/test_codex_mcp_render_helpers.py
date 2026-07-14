"""Compatibility CLI tests for the Codex MCP renderer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from helpers import PYTHON


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render-codex-mcp-block.py"


def run_renderer(*args: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [PYTHON, str(SCRIPT), "--context7-command", "npx", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_renderer_uses_normalized_proxy_without_api_key_argument():
    env = {
        **os.environ,
        "HTTP_PROXY": "http://127.0.0.1:7897",
        "HTTPS_PROXY": "http://127.0.0.1:7898",
        "ALL_PROXY": "socks5://127.0.0.1:7897",
    }
    result = run_renderer(env=env)
    assert result.returncode == 0, result.stderr
    assert (
        '[mcp_servers.context7]\nenabled = true\n'
        f'command = "{ROOT / "scripts" / "context7-mcp-bridge.py"}"\nargs = []'
    ) in result.stdout
    assert "abc" not in result.stdout
    assert 'HTTP_PROXY = "http://127.0.0.1:7897"' in result.stdout
    assert 'HTTPS_PROXY = "http://127.0.0.1:7898"' in result.stdout


def test_renderer_includes_optional_servers_only_when_requested():
    default = run_renderer()
    assert default.returncode == 0, default.stderr
    assert "[mcp_servers.devspace]" not in default.stdout

    enabled = run_renderer(
        "--devspace-url",
        "https://devspace.example/mcp",
    )
    assert enabled.returncode == 0, enabled.stderr
    assert "[mcp_servers.devspace]" in enabled.stdout
    assert 'url = "https://devspace.example/mcp"' in enabled.stdout
