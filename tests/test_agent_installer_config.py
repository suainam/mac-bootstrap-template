"""Agent installer orchestration checks."""

import os
import subprocess

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
    assert 'rm -f "$HOME/.local/bin/agent-prompt-mcp"' in content


def test_ensure_agent_dirs_runs_without_retired_pi_settings(tmp_path):
    """Retired Pi variables must not be referenced under `set -u`."""
    env = {
        "HOME": str(tmp_path),
        "DRY_RUN": "1",
        "CLAUDE_SETTINGS": str(tmp_path / ".claude/settings.json"),
        "CODEX_TOML": str(tmp_path / ".codex/config.toml"),
        "OPENCODE_CONFIG": str(tmp_path / ".config/opencode/opencode.json"),
        "REASONIX_CONFIG": str(tmp_path / ".reasonix/config.json"),
        "ANTIGRAVITY_SETTINGS": str(tmp_path / ".antigravity/settings.json"),
        "OPENCODE_PLUGINS_DIR": str(tmp_path / ".config/opencode/plugins"),
    }
    script = (
        "set -euo pipefail\n"
        f'. "{TEMPLATE}/scripts/lib/agent-shared.sh"\n'
        f'. "{TEMPLATE}/scripts/lib/agent-configure.sh"\n'
        "ensure_agent_dirs\n"
    )
    result = subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "unbound variable" not in result.stderr
    assert "''" not in result.stdout


def test_brewfile_includes_devspace_npm_package():
    content = open(os.path.join(TEMPLATE, "Brewfile")).read()
    assert 'npm "@waishnav/devspace"' in content
    assert 'brew "cloudflared"' in content
