"""Agent doctor and Python syntax-check script checks."""

import os
import tempfile
from pathlib import Path

from helpers import PYTHON, TEMPLATE, run


def read_template(*parts: str) -> str:
    return Path(TEMPLATE, *parts).read_text()


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
