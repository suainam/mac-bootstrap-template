"""Doctor exits according to required state, with optional features isolated."""

import os
import shutil
import subprocess
from pathlib import Path

from helpers import TEMPLATE


def doctor(tmp_path, *, host=False, fail=None, codex_config=False,
            opencode_installed=False):
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
    if opencode_installed:
        path = bin_dir / "opencode"
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    fake_python = bin_dir / "python-fake"
    fake_python.write_text('#!/bin/sh\ncase "$1" in *"$FAIL_SCRIPT") exit 1;; esac\nexit 0\n')
    fake_python.chmod(0o755)
    env = os.environ.copy()
    env.update(HOME=str(home), PATH=f"{bin_dir}:/usr/bin:/bin", PYTHON=str(fake_python),
               MAC_BOOTSTRAP_PRIVATE_DIR=str(tmp_path / "private"), FAIL_SCRIPT=fail or "NEVER_MATCH")
    # /bin/bash 3.2 is the oldest interpreter the production script runs under;
    # PATH bash may be 5.x where empty-array expansion differs (#225 defect class).
    result = subprocess.run(["/bin/bash", str(root / "scripts/agent-doctor.sh")],
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


def test_opencode_section_tolerates_unbound_rtk_paths(tmp_path):
    """pick_rtk_source must not crash under set -u when RTK path vars are unset.

    doctor-agent runs with `set -u`; install-agent-tooling.sh only defines
    CLAUDE_RTK/CODEX_RTK at install time, so a plain doctor run hits the
    OpenCode section without them and must still emit a verdict, not die.
    """
    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    (config_dir / "opencode.json").write_text("{}\n")
    (config_dir / "plugins").mkdir()
    (config_dir / "plugins" / "rtk.ts").write_text("// rtk\n")
    result = doctor(tmp_path, opencode_installed=True)
    assert "--- OpenCode ---" in result.stdout, result.stdout + result.stderr
    assert "unbound variable" not in result.stderr
    assert "AGENTS.md canonical rules content" in result.stdout


def test_verify_optional_args_reach_argparse_as_real_argv(tmp_path):
    """Optional --rtk/--adversarial-review args must reach agent-instructions.py.

    Before the length-guard fix, bash 3.2 expanded an empty optional-args array
    to one empty-string argv element; argparse then failed with "unrecognized
    arguments" and doctor reported a false MISS (#225 defect class).
    This test asserts the fake python receives exactly the fixed argv — no
    empty-string element when neither file exists, the real flags when both do.
    """
    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / ".config" / "opencode"
    config_dir.mkdir(parents=True)
    (config_dir / "opencode.json").write_text("{}\n")
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text("managed config\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = bin_dir / "calls.log"
    fake_python = bin_dir / "python-fake"
    # Log one bracketed line per argv element, so a leaked empty-string argument
    # (bash 3.2 empty-array expansion) surfaces as a bare "[]" line.
    fake_python.write_text(
        '#!/bin/sh\n'
        'for a in "$@"; do printf \'[%s]\\n\' "$a" >> "$CALLS_LOG"; done\n'
        'printf \'%s\\n\' "--END--" >> "$CALLS_LOG"\n'
        'exit 0\n'
    )
    fake_python.chmod(0o755)
    env = os.environ.copy()
    env.update(
        HOME=str(home), PATH=f"{bin_dir}:/usr/bin:/bin", PYTHON=str(fake_python),
        CALLS_LOG=str(calls_log), MAC_BOOTSTRAP_PRIVATE_DIR=str(tmp_path / "private"),
    )
    root = tmp_path / "template"
    scripts = Path(TEMPLATE) / "scripts"
    dest_scripts = root / "scripts"
    (dest_scripts / "lib").mkdir(parents=True)
    shutil.copyfile(scripts / "agent-doctor.sh", dest_scripts / "agent-doctor.sh")
    shutil.copyfile(scripts / "lib" / "agent-shared.sh", dest_scripts / "lib" / "agent-shared.sh")
    # doctor reads the manifest for target paths; without it both verify
    # targets resolve to empty strings and the sections SKIP.
    manifest_dst = root / "agent" / "agent-manifest.json"
    manifest_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(TEMPLATE) / "agent" / "agent-manifest.json", manifest_dst)
    # No ~/.codex/RTK.md and no bootstrap adversarial gate file exist here: both
    # optional arrays stay empty and must contribute zero argv elements.
    result = subprocess.run(["/bin/bash", str(root / "scripts/agent-doctor.sh")],
                            env=env, text=True, capture_output=True, check=False)
    verify_blocks = [
        block for block in calls_log.read_text().split("--END--\n")
        if "agent-instructions.py" in block and "verify" in block
    ]
    assert result.returncode != 0  # supply-chain FAIL is expected: minimal fixture
    assert len(verify_blocks) == 2, "doctor must verify both Codex and OpenCode instructions"
    for block in verify_blocks:
        argv = [line[1:-1] for line in block.splitlines() if line.startswith("[")]
        assert "" not in argv, f"empty-string argv leaked into verify: {argv}"
        assert "verify" in argv
