"""Interactive Homebrew upgrade wrapper checks."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_system_upgrade_refuses_non_tty_execution() -> None:
    result = subprocess.run(
        [str(ROOT / "scripts/system-upgrade.sh")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "interactive TTY" in result.stderr


def test_system_upgrade_keeps_password_and_brew_ownership_explicit() -> None:
    script = (ROOT / "scripts/system-upgrade.sh").read_text(encoding="utf-8")

    assert '"${BREW_BIN}" update' in script
    assert '"${BREW_BIN}" upgrade' in script
    assert "\nsudo " not in script
    assert "password" not in script.lower()
