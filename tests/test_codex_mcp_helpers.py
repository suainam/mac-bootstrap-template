"""Unit tests for Codex MCP config helper modules."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from helpers import PYTHON


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, rel_path: str):
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


sync_codex_mcp_config = load_module("sync_codex_mcp_config", "scripts/sync-codex-mcp-config.py")

sync_codex_mcp_config = load_module("sync_codex_mcp_config", "scripts/sync-codex-mcp-config.py")


def test_strip_managed_sections_removes_managed_tables_only():
    text = """
model = "gpt-5"

[mcp_servers.context-mode]
command = "old"

[mcp_servers.context-mode.tools.ctx_search]
approval_mode = "approve"

[other]
value = 1
""".strip()
    stripped = sync_codex_mcp_config.strip_managed_sections(text)
    assert '[mcp_servers.context-mode]' not in stripped
    assert '[mcp_servers.context-mode.tools.ctx_search]' not in stripped
    assert 'model = "gpt-5"' in stripped
    assert '[other]' in stripped


def test_build_output_adds_managed_block_after_existing_content():
    out = sync_codex_mcp_config.build_output('model = "gpt-5"\n', "# BLOCK\nvalue = 1\n")
    assert out.startswith('model = "gpt-5"\n\n')
    assert out.endswith("# BLOCK\nvalue = 1\n")


def test_strip_managed_sections_resets_skip_on_next_table():
    text = """
[mcp_servers.context7.env]
HTTP_PROXY = "http://127.0.0.1:7897"

[user]
name = "alice"
""".strip()
    stripped = sync_codex_mcp_config.strip_managed_sections(text)
    assert '[mcp_servers.context7.env]' not in stripped
    assert '[user]' in stripped


def test_strip_managed_sections_removes_x_servers():
    text = """
[mcp_servers.x-docs]
url = "https://docs.x.com/mcp"

[mcp_servers.xapi]
command = "npx"

[keep]
value = 1
""".strip()
    stripped = sync_codex_mcp_config.strip_managed_sections(text)
    assert "[mcp_servers.x-docs]" not in stripped
    assert "[mcp_servers.xapi]" not in stripped
    assert "[keep]" in stripped


def test_strip_managed_sections_removes_agent_prompt_library():
    text = """
[mcp_servers.agent-prompt-library]
command = "/home/alice/.local/bin/agent-prompt-mcp"

[mcp_servers.agent-prompt-library.tools.search_prompts]
approval_mode = "approve"

[keep]
value = 1
""".strip()
    stripped = sync_codex_mcp_config.strip_managed_sections(text)
    assert "[mcp_servers.agent-prompt-library]" not in stripped
    assert "[mcp_servers.agent-prompt-library.tools.search_prompts]" not in stripped
    assert "[keep]" in stripped


def test_sync_codex_main_writes_from_cli_args(tmp_path):
    config = tmp_path / "config.toml"
    block = tmp_path / "block.toml"
    config.write_text('model = "gpt-5"\n')
    block.write_text("# BEGIN\nx = 1\n# END\n")
    old_argv = sys.argv
    try:
        sys.argv = ["sync-codex-mcp-config.py", str(config), str(block)]
        rc = sync_codex_mcp_config.main()
    finally:
        sys.argv = old_argv
    assert rc == 0
