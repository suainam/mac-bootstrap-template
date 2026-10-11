"""Behavior tests for scripts/system-upgrade.sh process execution."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/system-upgrade.sh"


def make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_system_upgrade_refuses_non_tty_execution_without_yes() -> None:
    """Non-interactive execution without --yes / MAC_BOOTSTRAP_YES exits 2."""
    env = dict(os.environ)
    env.pop("MAC_BOOTSTRAP_YES", None)

    result = subprocess.run(
        [str(SCRIPT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 2
    assert "interactive TTY" in result.stderr


def test_system_upgrade_invalid_stage_exits_early_before_effects() -> None:
    """Invalid stage or missing argument in --only causes early error (code 2) without side effects."""
    env = dict(os.environ)
    env["MAC_BOOTSTRAP_YES"] = "1"

    # Unknown stage
    result = subprocess.run(
        [str(SCRIPT), "--only", "packages,nonexistent"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 2
    assert "Unknown stage 'nonexistent'" in result.stderr

    # Flag passed to --only
    result_flag = subprocess.run(
        [str(SCRIPT), "--only", "--yes"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result_flag.returncode == 2

    # Empty --only
    result_empty = subprocess.run(
        [str(SCRIPT), "--only", ""],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result_empty.returncode == 2


def test_system_upgrade_only_restricts_execution_and_prevents_unrelated_stages(tmp_path: Path) -> None:
    """Specifying --only bun runs only bun, not packages or other stages; dedupes repeated names."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    bun_log = tmp_path / "bun.log"
    make_executable(
        fake_bin / "bun",
        f"""#!/usr/bin/env bash
echo "$@" >> "{bun_log}"
exit 0
""",
    )

    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "MAC_BOOTSTRAP_YES": "1",
    }

    result = subprocess.run(
        [str(SCRIPT), "--only", "bun,bun"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "[ SUCCESS ]" in result.stdout
    assert result.stdout.count("bun          [ SUCCESS ]") == 1
    assert "packages" not in result.stdout
    assert "npm" not in result.stdout
    assert bun_log.exists()
    assert bun_log.read_text().count("update -g") == 1


def test_system_upgrade_missing_optional_tools_explicitly_skipped(tmp_path: Path) -> None:
    """Optional tools like bun, uv, claude report skipped when binaries are missing."""
    empty_bin = tmp_path / "empty_bin"
    empty_bin.mkdir()

    env = {
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
    assert "bun          [ SKIPPED ]" in result.stdout
    assert "uv           [ SKIPPED ]" in result.stdout
    assert "claude       [ SKIPPED ]" in result.stdout


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
        "PATH": f"{fake_bin}:/usr/bin:/bin",
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
    assert "packages     [ FAILED  ]" in result.stdout
    # 'brew upgrade' should NOT have been called because reconciliation failed
    executed_brew = brew_log.read_text() if brew_log.exists() else ""
    assert "brew update" in executed_brew
    assert "brew upgrade" not in executed_brew


def test_system_upgrade_independent_phase_progression_and_partial_failure_summary(tmp_path: Path) -> None:
    """When one stage fails (e.g. uv tool upgrade fails), subsequent independent stages still execute."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    bun_log = tmp_path / "bun.log"
    make_executable(
        fake_bin / "bun",
        f"""#!/usr/bin/env bash
echo "bun $@" >> "{bun_log}"
exit 0
""",
    )

    uv_log = tmp_path / "uv.log"
    make_executable(
        fake_bin / "uv",
        f"""#!/usr/bin/env bash
echo "uv $@" >> "{uv_log}"
exit 1
""",
    )

    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
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
    assert "uv           [ FAILED  ]" in result.stdout
    assert "bun          [ SUCCESS ]" in result.stdout
    assert uv_log.exists()
    assert bun_log.exists()
    assert "--only uv" in result.stdout


def test_system_upgrade_simulated_package_and_skill_failure_with_targeted_recovery(tmp_path: Path) -> None:
    """Simulated package and skill failure in one full run: exit code non-zero, summary accurate, recovery --only exact."""
    fake_root = tmp_path / "repo"
    fake_scripts = fake_root / "scripts"
    fake_scripts.mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_venv = fake_root / ".venv/bin"
    fake_venv.mkdir(parents=True)

    # Fake brew (update succeeds, upgrade succeeds, cleanup succeeds)
    make_executable(
        fake_bin / "brew",
        """#!/usr/bin/env bash
exit 0
""",
    )

    # brew-bundle.sh fails (ownership mismatch simulation)
    make_executable(
        fake_scripts / "brew-bundle.sh",
        """#!/usr/bin/env bash
echo "Error: Ownership mismatch detected" >&2
exit 1
""",
    )

    # Fake npm script (succeeds)
    make_executable(
        fake_scripts / "install-npm-global-packages.sh",
        """#!/usr/bin/env bash
exit 0
""",
    )

    # Fake npm binary
    make_executable(
        fake_bin / "npm",
        """#!/usr/bin/env bash
exit 0
""",
    )

    # Fake npx binary (succeeds)
    make_executable(
        fake_bin / "npx",
        """#!/usr/bin/env bash
exit 0
""",
    )

    # Fake skill_supply_chain.py (update-bundles fails simulation)
    skill_log = tmp_path / "skill.log"
    make_executable(
        fake_scripts / "skill_supply_chain.py",
        f"""#!/usr/bin/env bash
echo "$@" >> "{skill_log}"
if [[ "$1" == "update-bundles" ]]; then
  echo "Bundle update network failure" >&2
  exit 1
fi
exit 0
""",
    )

    make_executable(
        fake_venv / "python",
        """#!/usr/bin/env bash
exec bash "$@"
""",
    )

    # Fake make (for chrome stage, succeeds)
    make_executable(
        fake_bin / "make",
        """#!/usr/bin/env bash
exit 0
""",
    )

    fake_script = fake_scripts / "system-upgrade.sh"
    fake_script.write_text(SCRIPT.read_text(), encoding="utf-8")
    fake_script.chmod(0o755)

    env = {
        "PATH": f"{fake_bin}:{fake_venv}:/usr/bin:/bin",
        "BREW_BIN": str(fake_bin / "brew"),
        "PYTHON_BIN": str(fake_venv / "python"),
    }

    # Run full system upgrade with --yes (bun, uv, claude are not in fake_bin -> SKIPPED; npm, chrome -> SUCCESS; packages, skills -> FAILED)
    result = subprocess.run(
        [str(fake_script), "--yes"],
        cwd=fake_root,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert "System Upgrade Summary" in result.stdout
    assert "packages     [ FAILED  ]" in result.stdout
    assert "skills       [ FAILED  ]" in result.stdout
    assert "npm          [ SUCCESS ]" in result.stdout
    assert "chrome       [ SUCCESS ]" in result.stdout
    assert "bun          [ SKIPPED ]" in result.stdout
    assert "uv           [ SKIPPED ]" in result.stdout
    assert "claude       [ SKIPPED ]" in result.stdout

    # Recovery command specifies exact failed stages with --only packages,skills
    assert "--only packages,skills" in result.stdout

    # Now simulate recovery by fixing the causes and rerunning only the failed stages
    make_executable(
        fake_scripts / "brew-bundle.sh",
        """#!/usr/bin/env bash
exit 0
""",
    )
    make_executable(
        fake_scripts / "skill_supply_chain.py",
        f"""#!/usr/bin/env bash
echo "$@" >> "{skill_log}"
exit 0
""",
    )

    recovery_result = subprocess.run(
        [str(fake_script), "--yes", "--only", "packages,skills"],
        cwd=fake_root,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert recovery_result.returncode == 0
    assert "packages     [ SUCCESS ]" in recovery_result.stdout
    assert "skills       [ SUCCESS ]" in recovery_result.stdout
    # Unselected stages were NOT run
    assert "npm" not in recovery_result.stdout
    assert "chrome" not in recovery_result.stdout
    assert "bun" not in recovery_result.stdout
