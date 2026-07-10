"""Codex MCP rendering and managed-block checks."""

import os
import subprocess
import tempfile
from pathlib import Path

from helpers import PYTHON, TEMPLATE, run


def test_sync_codex_mcp_config_deduplicates_managed_tables():
    script = os.path.join(TEMPLATE, "scripts", "sync-codex-mcp-config.py")
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Path(tmpdir) / "config.toml"
        block = Path(tmpdir) / "block.toml"
        config.write_text(
            'model = "gpt-5"\n'
            '\n'
            '[mcp_servers.context-mode.tools.ctx_search]\n'
            'approval_mode = "approve"\n'
            '\n'
            '[mcp_servers.context7.env]\n'
            'HTTP_PROXY = "http://old"\n'
            '\n'
            '[mcp_servers.x-docs]\n'
            'url = "https://old.example/mcp"\n'
            '\n'
            '[mcp_servers.devspace]\n'
            'url = "https://old-devspace.example/mcp"\n'
            '\n'
            '[mcp_servers.codebase-memory-mcp]\n'
            'command = "old"\n'
        )
        block.write_text(
            '# BEGIN MAC-BOOTSTRAP MANAGED MCPS\n'
            '[mcp_servers.context-mode]\n'
            'command = "context-mode"\n'
            'args = []\n'
            '\n'
            '[mcp_servers.context-mode.tools.ctx_search]\n'
            'approval_mode = "approve"\n'
            '# END MAC-BOOTSTRAP MANAGED MCPS\n'
        )

        _, err, rc = run(f'"{PYTHON}" "{script}" "{config}" "{block}"')
        assert rc == 0, err
        content = config.read_text()

        assert content.count("[mcp_servers.context-mode.tools.ctx_search]") == 1
        assert content.count("[mcp_servers.context7.env]") == 0
        assert content.count("[mcp_servers.x-docs]") == 0
        assert content.count("[mcp_servers.devspace]") == 0
        assert content.count("# BEGIN MAC-BOOTSTRAP MANAGED MCPS") == 1
        assert 'model = "gpt-5"' in content


def test_render_codex_mcp_block_emits_proxy_variants():
    script = os.path.join(TEMPLATE, "scripts", "render-codex-mcp-block.py")
    env = {
        **os.environ,
        "HTTP_PROXY": "http://127.0.0.1:7897",
        "HTTPS_PROXY": "http://127.0.0.1:7897",
        "ALL_PROXY": "http://127.0.0.1:7897",
        "NO_PROXY": "localhost,127.0.0.1,::1",
    }
    result = subprocess.run(
        [PYTHON, script, "--context7-command", "npx"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert 'command = "npx"' in result.stdout
    assert 'args = ["-y", "@upstash/context7-mcp"]' in result.stdout
    assert 'all_proxy = "http://127.0.0.1:7897"' in result.stdout
    assert 'NO_PROXY = "localhost,127.0.0.1,::1"' in result.stdout
    assert '[mcp_servers.agent-prompt-library]' in result.stdout
    assert str(Path.home() / ".local/bin/agent-prompt-mcp") in result.stdout
    assert '[mcp_servers.agent-prompt-library.tools.search_prompts]' in result.stdout
    assert '[mcp_servers.x-docs]' in result.stdout
    assert 'url = "https://docs.x.com/mcp"' in result.stdout


def test_render_codex_mcp_block_includes_devspace_url():
    script = os.path.join(TEMPLATE, "scripts", "render-codex-mcp-block.py")
    result = subprocess.run(
        [PYTHON, script, "--context7-command", "npx", "--devspace-url", "https://devspace.suainam.eu.org/mcp"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "[mcp_servers.devspace]" in result.stdout
    assert 'url = "https://devspace.suainam.eu.org/mcp"' in result.stdout


def test_agent_mcp_uses_project_python_for_codex_helpers():
    content = open(os.path.join(TEMPLATE, "scripts", "lib", "agent-mcp.sh")).read()
    assert 'local python_bin="${PYTHON:-$BOOTSTRAP/.venv/bin/python}"' in content
    assert '"$python_bin" "$BOOTSTRAP/scripts/render-codex-mcp-block.py"' in content
    assert '"$python_bin" "$BOOTSTRAP/scripts/sync-codex-mcp-config.py"' in content


def test_agent_mcp_configures_prompt_library_for_json_agents():
    content = open(os.path.join(TEMPLATE, "scripts", "lib", "agent-mcp.sh")).read()
    assert 'write_mcp_config claude "$CLAUDE_MCP_JSON"' in content
    assert 'write_mcp_config opencode "$OPENCODE_CONFIG"' in content
    assert 'write_mcp_config pi "$PI_MCP_JSON"' in content
    assert 'write_mcp_config reasonix "$REASONIX_CONFIG"' in content
    assert 'write_mcp_config antigravity "$ANTIGRAVITY_MCP_JSON"' in content
    assert 'getPromptLibraryConfig' not in content
    assert 'code-review-graph' not in content
