"""Behavior tests for scripts/system-upgrade.sh process execution."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/system-upgrade.sh"


def make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_system_upgrade_refuses_non_tty_execution_without_yes() -> None:
    """Non-interactive execution without --yes / MAC_BOOTSTRAP_YES exits 2."""
    result = subprocess.run(
        [str(SCRIPT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "interactive TTY" in result.stderr


def test_system_upgrade_invalid_stage_exits_early_before_effects(tmp_path: Path) -> None:
    """Invalid stage in --only causes early error (code 2) without side effects."""
    result = subprocess.run(
        [str(SCRIPT), "--yes", "--only", "packages,nonexistent"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Unknown stage 'nonexistent'" in result.stderr


def test_system_upgrade_only_restricts_execution_and_prevents_unrelated_stages(tmp_path: Path) -> None:
    """Specifying --only bun runs only bun, not packages or other stages."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    # fake bun
    bun_log = tmp_path / "bun.log"
    make_executable(
        fake_bin / "bun",
        f"""#!/usr/bin/env bash
echo "$@" >> "{bun_log}"
exit 0
""",
    )

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "MAC_BOOTSTRAP_YES": "1",
    }

    result = subprocess.run(
        [str(SCRIPT), "--only", "bun"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "System Upgrade Summary" in result.stdout
    assert "bun          [ SUCCESS ]" in result.stdout
    # Unrequested stages should not appear in summary or execute
    assert "packages" not in result.stdout
    assert "npm" not in result.stdout
    assert bun_log.exists()
    assert "update -g" in bun_log.read_text()


def test_system_upgrade_missing_optional_tools_explicitly_skipped(tmp_path: Path) -> None:
    """Optional tools like bun, uv, claude report skipped when binaries are missing."""
    empty_bin = tmp_path / "empty_bin"
    empty_bin.mkdir()

    env = {
        **os.environ,
        "PATH": f"{empty_bin}:/usr/bin:/bin",
        "MAC_BOOTSTRAP_YES": "1",
    }

    result = subprocess.run(
        [str(SCRIPT), "--only", "bun,uv,claude"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "bun          [ SKIPPED ] (bun not installed)" in result.stdout
    assert "uv           [ SKIPPED ] (uv not installed)" in result.stdout
    assert "claude       [ SKIPPED ] (claude not installed)" in result.stdout


def test_system_upgrade_package_reconciliation_failure_halts_upgrade_and_reports_failed(tmp_path: Path) -> None:
    """When brew-bundle install fails (e.g. ownership error), subsequent package upgrades are skipped, stage fails."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    brew_log = tmp_path / "brew.log"
    make_executable(
        fake_bin / "brew",
        f"""#!/usr/bin/env bash
echo "brew $@" >> "{brew_log}"
exit 0
""",
    )

    # Fake repo with failing brew-bundle.sh
    fake_root = tmp_path / "repo"
    fake_scripts = fake_root / "scripts"
    fake_scripts.mkdir(parents=True)
    bundle_log = tmp_path / "bundle.log"
    make_executable(
        fake_scripts / "brew-bundle.sh",
        f"""#!/usr/bin/env bash
echo "brew-bundle $@" >> "{bundle_log}"
echo "Error: Ownership mismatch detected" >&2
exit 1
""",
    )

    fake_script = fake_scripts / "system-upgrade.sh"
    fake_script.write_text(SCRIPT.read_text(), encoding="utf-8")
    fake_script.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "BREW_BIN": str(fake_bin / "brew"),
    }

    result = subprocess.run(
        [str(fake_script), "--yes", "--only", "packages"],
        cwd=fake_root,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "packages     [ FAILED  ] (brew-bundle install reconciliation failed)" in result.stdout
    assert "Package reconciliation failed" in result.stderr
    # 'brew upgrade' should NOT have been called because reconciliation failed
    executed_brew = brew_log.read_text() if brew_log.exists() else ""
    assert "brew update" in executed_brew
    assert "brew upgrade" not in executed_brew


def test_system_upgrade_independent_phase_progression_and_partial_failure_summary(tmp_path: Path) -> None:
    """When one stage fails (e.g. uv tool upgrade fails), subsequent independent stages (e.g. bun) still execute."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    # bun succeeds
    bun_log = tmp_path / "bun.log"
    make_executable(
        fake_bin / "bun",
        f"""#!/usr/bin/env bash
echo "bun $@" >> "{bun_log}"
exit 0
""",
    )

    # uv fails
    uv_log = tmp_path / "uv.log"
    make_executable(
        fake_bin / "uv",
        f"""#!/usr/bin/env bash
echo "uv $@" >> "{uv_log}"
echo "uv network error" >&2
exit 1
""",
    )

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "MAC_BOOTSTRAP_YES": "1",
    }

    result = subprocess.run(
        [str(SCRIPT), "--only", "uv,bun"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "uv           [ FAILED  ] (uv tool upgrade failed)" in result.stdout
    assert "bun          [ SUCCESS ]" in result.stdout
    # Recovery suggestion printed
    assert "To retry only failed stages, run:" in result.stdout
    assert "--only uv" in result.stdout
    assert uv_log.exists()
    assert bun_log.exists()


def test_system_upgrade_skills_bundle_failure_prevents_distribute(tmp_path: Path) -> None:
    """In skills stage, if update-bundles fails, distribute is skipped, stage reports failure, overall non-zero."""
    fake_root = tmp_path / "repo"
    fake_scripts = fake_root / "scripts"
    fake_scripts.mkdir(parents=True)
    fake_venv = fake_root / ".venv/bin"
    fake_venv.mkdir(parents=True)

    skills_log = tmp_path / "skills.log"
    make_executable(
        fake_scripts / "skill_supply_chain.py",
        f"""#!/usr/bin/env bash
echo "$@" >> "{skills_log}"
if [[ "$1" == "update-bundles" ]]; then
  echo "Bundle fetch failed: upstream 503" >&2
  exit 1
fi
exit 0
""",
    )

    # Fake python that runs the script
    make_executable(
        fake_venv / "python",
        """#!/usr/bin/env bash
exec bash "$@"
""",
    )

    fake_script = fake_scripts / "system-upgrade.sh"
    fake_script.write_text(SCRIPT.read_text(), encoding="utf-8")
    fake_script.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_venv}:/usr/bin:/bin",
        "PYTHON_BIN": str(fake_venv / "python"),
    }

    result = subprocess.run(
        [str(fake_script), "--yes", "--only", "skills"],
        cwd=fake_root,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "skills       [ FAILED  ]" in result.stdout
    assert "Distribute skipped due to bundle update failure" in result.stderr
    log_content = skills_log.read_text()
    assert "update-bundles" in log_content
    # distribute was NOT invoked because update-bundles failed
    assert "distribute" not in log_content
