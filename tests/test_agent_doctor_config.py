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
