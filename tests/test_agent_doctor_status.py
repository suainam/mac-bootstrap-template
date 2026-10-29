"""Doctor exits according to required state, with optional features isolated."""

import os
import shutil
import subprocess
from pathlib import Path

from helpers import TEMPLATE


def doctor(tmp_path, *, host=False, fail=None, codex_config=False):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    root = tmp_path / "template"
    for name in (
        "scripts/agent-doctor.sh", "scripts/lib/agent-shared.sh",
        "agent/agent-manifest.json", "agent-skills/registry/sources.jsonc",
        "agent-skills/registry/targets.jsonc", "agent/quality-gates/manifest.jsonc",
        "scripts/agent-quality-gate.sh", "scripts/neat-freak-gate.sh",
        "scripts/knowledge-record-gate.sh",
    ):
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(TEMPLATE) / name, destination)
    if codex_config:
        (home / ".codex").mkdir()
        (home / ".codex/config.toml").write_text("managed config")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("codebase-memory-mcp", "npm", "npx", "node"):
        path = bin_dir / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    if host:
        path = bin_dir / "codex"
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    fake_python = bin_dir / "python-fake"
    fake_python.write_text('#!/bin/sh\ncase "$1" in *"$FAIL_SCRIPT") exit 1;; esac\nexit 0\n')
    fake_python.chmod(0o755)
    env = os.environ.copy()
    env.update(HOME=str(home), PATH=f"{bin_dir}:/usr/bin:/bin", PYTHON=str(fake_python),
               MAC_BOOTSTRAP_PRIVATE_DIR=str(tmp_path / "private"), FAIL_SCRIPT=fail or "NEVER_MATCH")
    result = subprocess.run(["bash", str(root / "scripts/agent-doctor.sh")],
                            env=env, text=True, capture_output=True, check=False)
    return result


def test_missing_required_active_host_configuration_fails(tmp_path):
    result = doctor(tmp_path, host=True, fail="agent-instructions.py")
    assert "MISS AGENTS.md canonical rules content" in result.stdout
    assert "MISS codex MCP config" in result.stdout
    assert result.returncode != 0


def test_missing_optional_capabilities_do_not_fail(tmp_path):
    result = doctor(tmp_path)
    assert "SKIP prompt index" in result.stdout
    assert "SKIP Codex" in result.stdout
    assert result.returncode == 0, result.stdout + result.stderr


def test_skill_supply_chain_failure_fails_without_any_host(tmp_path):
    result = doctor(tmp_path, fail="skill_supply_chain.py")
    assert "FAIL skill supply-chain check" in result.stdout
    assert result.returncode != 0


def test_invalid_managed_mcp_audit_fails(tmp_path):
    result = doctor(tmp_path, host=True, codex_config=True, fail="agent_mcp_runtime.py")
    assert "MISS codex managed MCP state" in result.stdout
    assert result.returncode != 0
