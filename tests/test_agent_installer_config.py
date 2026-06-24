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
