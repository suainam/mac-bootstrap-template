"""Agent doctor and Python syntax-check script checks."""

import json
import os
import tempfile
from pathlib import Path

from helpers import PYTHON, TEMPLATE, run


def read_template(*parts: str) -> str:
    return Path(TEMPLATE, *parts).read_text()


def test_antigravity_manifest_uses_agy_mcp_config_path():
    manifest = json.loads(read_template("agent", "agent-manifest.json"))
    assert manifest["agents"]["antigravity"]["paths"]["mcp"] == "~/.gemini/config/mcp_config.json"


def test_global_instruction_paths_use_canonical_agents_source():
    manifest = json.loads(read_template("agent", "agent-manifest.json"))
    assert manifest["canonical"]["rules_file"] == "agent/rules/AGENTS.md"
    assert manifest["agents"]["claude"]["paths"]["agents_md"] == "~/.claude/AGENTS.md"
    assert manifest["agents"]["claude"]["paths"]["instructions"] == "~/.claude/CLAUDE.md"
    assert manifest["agents"]["codex"]["paths"]["instructions"] == "~/.codex/AGENTS.md"
    assert manifest["agents"]["opencode"]["paths"]["instructions"] == "~/.config/opencode/AGENTS.md"
    assert manifest["agents"]["pi"]["paths"]["instructions"] == "~/.pi/agent/AGENTS.md"
    assert manifest["agents"]["antigravity"]["paths"]["global_instructions"] == "~/.gemini/GEMINI.md"

    # Workspaces maintain their own instructions; manifest must not declare global workspace instruction targets
    for agent_cfg in manifest.get("agents", {}).values():
        paths = agent_cfg.get("paths", {})
        assert "work_instructions" not in paths
        assert "workspace_instructions" not in paths


def test_installer_does_not_generate_workspace_instruction_copies():
    configure = read_template("scripts", "lib", "agent-configure.sh")
    installer = read_template("scripts", "install-agent-tooling.sh")
    doctor = read_template("scripts", "agent-doctor.sh")
    assert "write_markdown_file \"$WORK_GEMINI\"" not in configure
    assert "write_markdown_file \"$WORK_REASONIX\"" not in configure
    assert "WORK_AGENTS=\"$WORK_ROOT/AGENTS.md\"" not in installer
    assert "WORK_GEMINI" not in installer
    assert "WORK_REASONIX" not in installer
    assert "WORK_AGENTS" not in installer
    assert "WORK_GEMINI" not in configure
    assert "WORK_REASONIX" not in configure
    assert "WORK_AGENTS" not in configure
    assert "WORK_GEMINI" not in doctor
    assert "WORK_REASONIX" not in doctor
    assert "WORK_AGENTS" not in doctor


def test_agent_doctor_checks_global_instruction_symlinks():
    content = read_template("scripts", "agent-doctor.sh")
    assert 'check_symlink "AGENTS.md" "$CLAUDE_AGENTS_MD"' in content
    assert 'check_symlink "CLAUDE.md → AGENTS.md" "$CLAUDE_MD"' in content
    assert 'check_symlink "global GEMINI.md → canonical AGENTS.md" "$GLOBAL_GEMINI"' in content
    assert 'check_symlink "OMP AGENTS.md" "$OMP_AGENT_DIR/AGENTS.md"' in content

def test_check_python_syntax_parses_files():
    script = os.path.join(TEMPLATE, "scripts", "check-python-syntax.py")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "ok.py"
        path.write_text("x = 1\n")
        out, err, rc = run(f'"{PYTHON}" "{script}" "{path}"')
        assert rc == 0, err
        assert f"ok {path}" in out


def test_doctor_uses_capability_checks():
    content = read_template("scripts", "doctor.sh")
    assert 'PYTHON="${PYTHON:-$DIR/.venv/bin/python}"' in content
    assert '"$PYTHON" "$DIR/scripts/run-doctor-checks.py"' in content
    assert 'run-doctor-checks.py' in content
    assert 'doctor-manifest.json' in content


def test_agent_doctor_checks_prompt_mcp_helper():
    content = read_template("scripts", "agent-doctor.sh")
    assert 'agent-prompt helper' in content
    assert 'agent-prompt-mcp helper' not in content


def test_opencode_v2_rtk_plugin_uses_v2_api_without_shell_interpolation():
    plugin = read_template("agent", "opencode", "plugins", "rtk.ts")
    assert 'from "@opencode/plugin"' in plugin
    assert "Plugin.define" in plugin
    assert 'ctx.tool.hook("execute.before"' in plugin
    assert 'execFileAsync("rtk", ["rewrite", input.command])' in plugin
    assert "Bun.$" not in plugin


def test_opencode_v2_installer_removes_v1_dependency_and_plugin_key():
    configure = read_template("scripts", "lib", "agent-configure.sh")
    assert 'npm uninstall --prefix "$(dirname "$OPENCODE_CONFIG")" --save @opencode-ai/plugin' in configure
    assert 'npm install --prefix "$(dirname "$OPENCODE_CONFIG")" --save @opencode/plugin@2' in configure
    assert "delete data.plugin" in configure
    assert 'data.plugins = [...new Set(plugins)]' in configure


def test_opencode_v2_doctor_rejects_v1_dependency_and_plugin_key():
    doctor = read_template("scripts", "agent-doctor.sh")
    assert '"plugin"[[:space:]]*:' in doctor
    assert '"@opencode-ai/plugin"' in doctor


def test_agent_doctor_delegates_mcp_validation_to_runtime_audit():
    content = read_template("scripts", "agent-doctor.sh")
    assert "audit_mcp_config()" in content
    assert 'agent_mcp_runtime.py"' in content
    assert "\n    audit\n" in content
    assert 'audit_mcp_config codex "$CODEX_TOML" --hooks-path "$CODEX_HOOKS"' in content
    assert 'audit_mcp_config claude "$CLAUDE_MCP_JSON"' in content
    assert 'check_contains "config.toml CBM"' not in content
    assert "--check-executables" in content


def test_agent_doctor_avoids_empty_array_expansion_under_nounset():
    content = read_template("scripts", "agent-doctor.sh")
    assert "curl_args=(-fsS" in content
    assert 'curl "${curl_args[@]}"' in content
    assert '"${auth_header[@]}"' not in content
    assert 'local -a audit_args=(' in content
    assert '"${policy_args[@]}"' not in content


def test_agent_doctor_resolves_context7_before_freezing_audit_arguments():
    content = read_template("scripts", "agent-doctor.sh")
    function = content[content.index("audit_mcp_config()") : content.index("check_max_lines()")]

    assert function.index("command -v context7-mcp") < function.index("local -a audit_args=(")


def test_agent_doctor_continues_after_agentshield_findings():
    content = read_template("scripts", "agent-doctor.sh")
    assert 'scan_agentshield()' in content
    assert '--save-baseline "$scan_baseline"' in content
    assert '"$HOME/.claude"' in content
    assert 'private/agent/agentshield.baseline.json' in content
    assert 'AgentShield acknowledged findings unchanged' in content
    assert 'AgentShield new or changed findings' in content
    assert 'AgentShield baseline verification failed' in content
    assert 'npx "${scan_args[@]}" >/dev/null 2>/dev/null' in content
    assert 'trap \'rm -rf -- "$scan_dir"' in content
    assert 'scan_report' not in content


def test_doctor_manifest_captures_overrides():
    content = read_template("scripts", "doctor-manifest.json")
    assert '"ripgrep": "rg"' in content
    assert '"claude-code"' in content
    assert '"cc-switch"' in content


def test_run_doctor_checks_parses_manifest():
    content = read_template("scripts", "run-doctor-checks.py")
    assert 'formula_command_overrides' in content
    assert 'cask_overrides' in content
    assert 'standalone_clis' in content


def test_agent_shared_does_not_load_web_only_devspace_mcp():
    content = read_template("scripts", "lib", "agent-shared.sh")
    assert "load_devspace_mcp_private_env" not in content
    assert "DEVSPACE_MCP_URL" not in content


def test_makefile_exposes_devspace_targets_and_checks_script():
    content = read_template("Makefile")
    assert "devspace-check:" in content
    assert "devspace-run:" in content
    assert "devspace-doctor:" in content
    assert "devspace-tunnel:" in content
    assert "$(MAKE) syntax-check" in content
    assert "./scripts/devspace-local.sh check" in content
    assert "./scripts/devspace-local.sh run" in content
    assert "./scripts/devspace-local.sh doctor" in content
    assert "./scripts/devspace-local.sh tunnel-run" in content
