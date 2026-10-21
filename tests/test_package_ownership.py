"""Behavior tests for package manager ownership under pure Homebrew (Issue #198)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = TEMPLATE / "scripts"
OWNERSHIP_SCRIPT = SCRIPTS_DIR / "package-ownership.sh"
BREW_BUNDLE_SCRIPT = SCRIPTS_DIR / "brew-bundle.sh"


def test_package_ownership_all_formulas_default_to_brew() -> None:
    """Under pure Homebrew architecture, all formulas default to brew ownership."""
    for formula in ["git", "uv", "docker", "rclone", "rustic", "homebrew/core/uv"]:
        res = subprocess.run(
            [str(OWNERSHIP_SCRIPT), "owner", formula],
            capture_output=True,
            text=True,
            check=True,
        )
        assert res.stdout.strip() == "brew", f"{formula} did not resolve to brew"


def test_package_ownership_list_zb_is_empty() -> None:
    """Zerobrew formula list is empty after cutover."""
    res = subprocess.run(
        [str(OWNERSHIP_SCRIPT), "list-zb"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == ""


def test_normal_reconcile_installs_via_brew_without_skips(tmp_path: Path) -> None:
    """brew-bundle.sh install does not skip declared formulas."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    mock_brew_log = tmp_path / "brew.log"
    mock_brew = bin_dir / "brew"
    mock_brew.write_text(f"""#!/usr/bin/env bash
echo "brew $@" >> "{mock_brew_log}"
if [ "$1" = "bundle" ] && [ "$2" = "install" ]; then
    echo "bundle install ok" >> "{mock_brew_log}"
    exit 0
fi
exit 0
""")
    mock_brew.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(tmp_path)

    res = subprocess.run(
        [str(BREW_BUNDLE_SCRIPT), "install"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0
    log = mock_brew_log.read_text()
    assert "bundle install ok" in log
