"""Tests for bootstrap CLI behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"


def test_install_sh_help() -> None:
    result = subprocess.run(
        ["/bin/bash", str(INSTALL_SH), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Usage: ./install.sh" in result.stdout


def test_install_sh_unknown_option() -> None:
    result = subprocess.run(
        ["/bin/bash", str(INSTALL_SH), "--invalid-flag"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Unknown option: --invalid-flag" in result.stderr
