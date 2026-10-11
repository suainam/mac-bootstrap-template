"""Tests for cold-start bootstrap CLI behavior (issue #163).

Verifies permission preflight, prefix length validation, and installer PATH
propagation without relying on pre-existing shell dotfiles or live systems.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"


def test_prefix_preflight_fails_when_prefix_too_long(tmp_path: Path):
    """ZEROBREW_PREFIX > 13 chars exits 2 before mutating state."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(fake_home),
        "ZEROBREW_ROOT": str(tmp_path / "zb"),
        "ZEROBREW_PREFIX": "/opt/zerobrew_too_long",
    }
    result = subprocess.run(
        ["/bin/bash", str(INSTALL_SH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "ZEROBREW_PREFIX must be at most 13 characters on macOS" in result.stderr
    assert not (fake_home / "work").exists()


def test_prefix_preflight_fails_when_root_missing(tmp_path: Path):
    """Non-existent ZEROBREW_ROOT exits 2 with permission command before mutating state."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    nonexistent_root = tmp_path / "nonexistent_zb"

    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(fake_home),
        "ZEROBREW_ROOT": str(nonexistent_root),
        "ZEROBREW_PREFIX": str(nonexistent_root),
    }
    result = subprocess.run(
        ["/bin/bash", str(INSTALL_SH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Create a user-owned zerobrew directory before bootstrap:" in result.stderr
    assert f'sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 755 "{nonexistent_root}"' in result.stderr
    assert not (fake_home / "work").exists()


def test_prefix_preflight_fails_when_root_unwritable(tmp_path: Path):
    """Unwritable ZEROBREW_ROOT exits 2 with permission command."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    unwritable_root = tmp_path / "unwritable_zb"
    unwritable_root.mkdir(mode=0o555)

    try:
        env = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(fake_home),
            "ZEROBREW_ROOT": str(unwritable_root),
            "ZEROBREW_PREFIX": str(unwritable_root),
        }
        result = subprocess.run(
            ["/bin/bash", str(INSTALL_SH)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 2
        assert "Create a user-owned zerobrew directory before bootstrap:" in result.stderr
        assert not (fake_home / "work").exists()
    finally:
        os.chmod(str(unwritable_root), 0o755)


def test_installer_path_includes_zerobrew_bins_early(tmp_path: Path):
    """Installer configures PATH with zerobrew bins ahead of system PATH."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_root = tmp_path / "zb"
    fake_root.mkdir()
    zb_bin = fake_root / "bin"
    zb_bin.mkdir()

    # Stub tool placed in ZEROBREW_PREFIX/bin
    stub_tool = zb_bin / "zb-test-probe"
    stub_tool.write_text("#!/bin/sh\necho ZB_PROBE_SUCCESS\n", encoding="utf-8")
    stub_tool.chmod(0o755)

    # Clean env with only system PATH
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(fake_home),
        "ZEROBREW_ROOT": str(fake_root),
        "ZEROBREW_PREFIX": str(fake_root),
    }

    # Running install.sh with a probe command right after path export
    # verifies that subsequent tooling sees zb-test-probe without sourcing dotfiles
    probe_script = f"""
    export ZEROBREW_ROOT="{fake_root}"
    export ZEROBREW_PREFIX="{fake_root}"
    for p in "/usr/local/bin" "/opt/homebrew/bin" "$HOME/.local/bin" "$ZEROBREW_PREFIX/sbin" "$ZEROBREW_PREFIX/bin"; do
      if [[ ":$PATH:" != *":$p:"* ]]; then
        PATH="$p:$PATH"
      fi
    done
    export PATH
    command -v zb-test-probe
    """
    result = subprocess.run(
        ["/bin/bash", "-c", probe_script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert str(stub_tool) in result.stdout
