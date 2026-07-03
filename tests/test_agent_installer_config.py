"""Agent installer orchestration checks."""

import os

from helpers import TEMPLATE


def test_install_agent_tooling_is_thin_orchestrator():
    content = open(os.path.join(TEMPLATE, "scripts", "install-agent-tooling.sh")).read()
    assert '. "$BOOTSTRAP/scripts/lib/agent-mcp.sh"' in content
    assert '. "$BOOTSTRAP/scripts/lib/agent-configure.sh"' in content
    assert "configure_all_mcp" in content
    assert len(content.splitlines()) < 250


def test_install_agent_tooling_links_prompt_helpers():
    content = open(os.path.join(TEMPLATE, "scripts", "lib", "agent-configure.sh")).read()
    assert 'ln -sf "$BOOTSTRAP/scripts/agent-prompt.sh" "$HOME/.local/bin/agent-prompt"' in content
    assert 'ln -sf "$BOOTSTRAP/scripts/agent-prompt-mcp.sh" "$HOME/.local/bin/agent-prompt-mcp"' in content


def test_install_agent_tooling_loads_private_x_mcp_env():
    content = open(os.path.join(TEMPLATE, "scripts", "install-agent-tooling.sh")).read()
    assert "load_x_mcp_private_env" in content


def test_x_mcp_bridge_loads_private_env():
    content = open(os.path.join(TEMPLATE, "scripts", "x-mcp-bridge.sh")).read()
    assert "load_x_mcp_private_env" in content
    assert 'export REDIRECT_URI="$X_MCP_CALLBACK_URL"' in content
    assert 'exec npx -y @xdevplatform/xurl mcp https://api.x.com/mcp' in content
