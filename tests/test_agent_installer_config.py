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


def test_configure_antigravity_settings_merges_template_and_private(tmp_path):
    import json

    settings_path = tmp_path / ".gemini/antigravity-cli/settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "model": "Gemini 4 Hydrogen (Medium)",
                "trustedWorkspaces": ["/tmp/existing"],
                "permissions": {"allow": ["command(git)"]},
            }
        ),
        encoding="utf-8",
    )
    private_dir = tmp_path / "private"
    sample_work = str(tmp_path / "work")
    (private_dir / "agent/agy").mkdir(parents=True)
    (private_dir / "agent/agy/settings.json").write_text(
        json.dumps(
            {
                "showTips": False,
                "trustedWorkspaces": [sample_work],
                "permissions": {"allow": [f"read_file({sample_work})"]},
            }
        ),
        encoding="utf-8",
    )
    env = {
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
        "BOOTSTRAP": TEMPLATE,
        "MAC_BOOTSTRAP_PRIVATE_DIR": str(private_dir),
        "ANTIGRAVITY_SETTINGS": str(settings_path),
    }
    script = (
        "set -euo pipefail\n"
        f'BOOTSTRAP="{TEMPLATE}"\n'
        f'. "{TEMPLATE}/scripts/lib/agent-shared.sh"\n'
        f'. "{TEMPLATE}/scripts/lib/agent-mcp.sh"\n'
        "configure_antigravity_settings_file\n"
    )
    result = subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    merged = json.loads(settings_path.read_text(encoding="utf-8"))
    assert merged["agentMode"] == "auto"
    assert merged["enableTerminalSandbox"] is True
    assert merged["toolPermission"] == "proceed-in-sandbox"
    assert merged["artifactReviewPolicy"] == "always-proceed"
    assert merged["showTips"] is False
    assert merged["model"] == "Gemini 4 Hydrogen (Medium)"
    assert merged["trustedWorkspaces"] == ["/tmp/existing", sample_work]
    assert merged["permissions"]["allow"] == [
        "command(git)",
        "mcp(*)",
        "read_url(*)",
        f"read_file({sample_work})",
    ]
    assert str(tmp_path / ".gemini/antigravity-cli/skills") in merged["skills"]

