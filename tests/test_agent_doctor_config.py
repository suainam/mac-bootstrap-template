"""Agent doctor and Python syntax-check script checks."""

import os
import tempfile
from pathlib import Path

from helpers import PYTHON, TEMPLATE, run


def test_check_python_syntax_parses_files():
    script = os.path.join(TEMPLATE, "scripts", "check-python-syntax.py")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "ok.py"
        path.write_text("x = 1\n")
        out, err, rc = run(f'"{PYTHON}" "{script}" "{path}"')
        assert rc == 0, err
        assert f"ok {path}" in out


def test_doctor_uses_capability_checks():
    content = open(os.path.join(TEMPLATE, "scripts", "doctor.sh")).read()
    assert 'PYTHON="${PYTHON:-$DIR/.venv/bin/python}"' in content
    assert '"$PYTHON" "$DIR/scripts/run-doctor-checks.py"' in content
    assert 'run-doctor-checks.py' in content
    assert 'doctor-manifest.json' in content


def test_agent_doctor_checks_prompt_mcp_helper():
    content = open(os.path.join(TEMPLATE, "scripts", "agent-doctor.sh")).read()
    assert 'agent-prompt helper' in content
    assert 'agent-prompt-mcp helper' in content


def test_agent_doctor_delegates_mcp_validation_to_runtime_audit():
    content = open(os.path.join(TEMPLATE, "scripts", "agent-doctor.sh")).read()
    assert "audit_mcp_config()" in content
    assert 'agent_mcp_runtime.py" audit' in content
    assert 'audit_mcp_config codex "$CODEX_TOML" --hooks-path "$CODEX_HOOKS"' in content
    assert 'audit_mcp_config claude "$CLAUDE_MCP_JSON"' in content
    assert 'check_contains "config.toml CBM"' not in content
    assert "--check-executables" in content


def test_agent_doctor_avoids_empty_array_expansion_under_nounset():
    content = open(os.path.join(TEMPLATE, "scripts", "agent-doctor.sh")).read()
    assert "curl_args=(-fsS" in content
    assert 'curl "${curl_args[@]}"' in content
    assert '"${auth_header[@]}"' not in content


def test_agent_doctor_continues_after_agentshield_findings():
    content = open(os.path.join(TEMPLATE, "scripts", "agent-doctor.sh")).read()
    assert 'run npx ecc-agentshield scan || AGENTSHIELD_RC=$?' in content
    assert 'continuing configuration health checks' in content
    assert content.index('continuing configuration health checks') < content.index('=== Configuration Health ===')


def test_doctor_manifest_captures_overrides():
    content = open(os.path.join(TEMPLATE, "scripts", "doctor-manifest.json")).read()
    assert '"ripgrep": "rg"' in content
    assert '"claude-code"' in content
    assert '"cc-switch"' in content


def test_run_doctor_checks_parses_manifest():
    content = open(os.path.join(TEMPLATE, "scripts", "run-doctor-checks.py")).read()
    assert 'formula_command_overrides' in content
    assert 'cask_overrides' in content
    assert 'standalone_clis' in content


def test_agent_shared_loads_devspace_mcp_from_private_runtime():
    content = open(os.path.join(TEMPLATE, "scripts", "lib", "agent-shared.sh")).read()
    assert "load_devspace_mcp_private_env()" in content
    assert 'DEVSPACE_MCP_URL={base_url}/mcp' in content
    assert 'DEVSPACE_MCP_ENABLE=1' in content


def test_makefile_exposes_devspace_targets_and_checks_script():
    content = open(os.path.join(TEMPLATE, "Makefile")).read()
    assert "devspace-check:" in content
    assert "devspace-run:" in content
    assert "devspace-doctor:" in content
    assert "devspace-tunnel:" in content
    assert "bash -n scripts/devspace-local.sh" in content
    assert "./scripts/devspace-local.sh check" in content
    assert "./scripts/devspace-local.sh run" in content
    assert "./scripts/devspace-local.sh doctor" in content
    assert "./scripts/devspace-local.sh tunnel-run" in content
