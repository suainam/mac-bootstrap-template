"""Tests for cold-start bootstrap CLI behavior (issue #163).

Verifies permission preflight, short-prefix validation, and installer PATH
propagation to downstream tooling in clean environments without dotfiles.
"""

import os
import shutil
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"


def make_short_zb_path() -> Path:
    """Generate a short temporary path strictly <= 13 characters on macOS."""
    token = uuid.uuid4().hex[:5]
    path = Path(f"/tmp/z{token}")
    assert len(str(path)) <= 13, f"Path exceeds 13 characters: {path}"
    return path


def test_prefix_preflight_fails_when_prefix_too_long(tmp_path: Path):
    """ZEROBREW_PREFIX > 13 chars exits 2 before mutating state."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(fake_home),
        "ZEROBREW_ROOT": "/tmp/z_toolong",
        "ZEROBREW_PREFIX": "/tmp/z_too_long_prefix",
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
    """Non-existent short ZEROBREW_ROOT (<= 13 chars) exits 2 with permission command."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    short_zb = make_short_zb_path()
    assert not short_zb.exists()

    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(fake_home),
        "ZEROBREW_ROOT": str(short_zb),
        "ZEROBREW_PREFIX": str(short_zb),
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
    assert f'sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 755 "{short_zb}"' in result.stderr
    # Must have passed length check (not failed with >13 error)
    assert "ZEROBREW_PREFIX must be at most 13 characters on macOS" not in result.stderr
    assert not (fake_home / "work").exists()


def test_prefix_preflight_fails_when_root_unwritable(tmp_path: Path):
    """Unwritable short ZEROBREW_ROOT (<= 13 chars) exits 2 with permission command."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    short_zb = make_short_zb_path()
    short_zb.mkdir(mode=0o555)

    try:
        env = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(fake_home),
            "ZEROBREW_ROOT": str(short_zb),
            "ZEROBREW_PREFIX": str(short_zb),
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
        assert f'sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 755 "{short_zb}"' in result.stderr
        assert "ZEROBREW_PREFIX must be at most 13 characters on macOS" not in result.stderr
        assert not (fake_home / "work").exists()
    finally:
        os.chmod(str(short_zb), 0o755)
        shutil.rmtree(str(short_zb), ignore_errors=True)


def test_cold_installer_reaches_downstream_tooling_with_zb_path(tmp_path: Path):
    """Actual installer in clean environment exports ZEROBREW_PREFIX/bin ahead of system PATH."""
    sandbox = tmp_path / "repo"
    sandbox.mkdir()

    # Copy actual install.sh
    shutil.copy2(str(INSTALL_SH), str(sandbox / "install.sh"))

    # Minimal workspace entrypoints
    (sandbox / "workspace").mkdir()
    (sandbox / "workspace" / "Makefile").write_text("# makefile\n", encoding="utf-8")
    (sandbox / "workspace" / "PROJECTS_GUIDE.md").write_text("# guide\n", encoding="utf-8")

    # Safe stub scripts
    scripts_dir = sandbox / "scripts"
    scripts_dir.mkdir()
    spy_log = tmp_path / "spy.log"

    # brew-bundle installs mock uv into ZEROBREW_PREFIX/bin
    brew_bundle = scripts_dir / "brew-bundle.sh"
    brew_bundle.write_text(
        "#!/usr/bin/env bash\n"
        "mkdir -p \"$ZEROBREW_PREFIX/bin\"\n"
        "cat <<'EOF' > \"$ZEROBREW_PREFIX/bin/uv\"\n"
        "#!/usr/bin/env bash\n"
        "echo \"mock-uv-0.4.0\"\n"
        "EOF\n"
        "chmod +x \"$ZEROBREW_PREFIX/bin/uv\"\n"
        f"echo \"BUNDLE_PROFILE=${{MAC_BOOTSTRAP_PROFILE:-}}\" >> \"{spy_log}\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    brew_bundle.chmod(0o755)

    # setup-python-venv verifies uv is in PATH
    setup_venv = scripts_dir / "setup-python-venv.sh"
    setup_venv.write_text(
        "#!/usr/bin/env bash\n"
        "UV_BIN=\"$(command -v uv || true)\"\n"
        f"echo \"VENV_UV_BIN=$UV_BIN\" >> \"{spy_log}\"\n"
        f"echo \"VENV_PROFILE=${{MAC_BOOTSTRAP_PROFILE:-}}\" >> \"{spy_log}\"\n"
        "if [ -z \"$UV_BIN\" ]; then\n"
        "  echo \"Missing uv in PATH\" >&2\n"
        "  exit 2\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    setup_venv.chmod(0o755)

    for stub_name in [
        "install-external-tools.sh",
        "ssh-manage.sh",
        "switch-terminal-theme.sh",
        "configure-proxies.sh",
        "clear-proxies.sh",
        "render-configs.sh",
    ]:
        stub = scripts_dir / stub_name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)

    for mod in [
        "desktop/hammerspoon",
        "terminals/ghostty",
        "multiplexer/herder",
        "editors/vscode",
        "infra/docker",
    ]:
        d = sandbox / mod
        d.mkdir(parents=True)
        s = d / ("install-extensions.sh" if "vscode" in mod else "install.sh")
        s.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        s.chmod(0o755)

    # External command stubs directory
    ext_bin = tmp_path / "bin"
    ext_bin.mkdir()
    for cmd in ["xcode-select", "brew", "git"]:
        s = ext_bin / cmd
        s.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        s.chmod(0o755)

    # Short prefix <= 13 chars
    short_zb = make_short_zb_path()
    short_zb.mkdir()
    (short_zb / "bin").mkdir()

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    try:
        for profile in ["home", "work"]:
            spy_log.write_text("", encoding="utf-8")
            # Cold shell: no dotfiles, minimal PATH with zb path present later to test reordering
            env = {
                "PATH": f"{ext_bin}:/usr/bin:/bin:{short_zb}/bin",
                "HOME": str(fake_home),
                "ZEROBREW_ROOT": str(short_zb),
                "ZEROBREW_PREFIX": str(short_zb),
                "GIT_NAME": "Test User",
                "GIT_EMAIL": "test@example.com",
            }
            result = subprocess.run(
                ["/bin/bash", str(sandbox / "install.sh"), "--yes", "--profile", profile],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            assert result.returncode == 0, f"Failed for profile {profile}: {result.stderr}"
            log_content = spy_log.read_text(encoding="utf-8")
            assert f"BUNDLE_PROFILE={profile}" in log_content
            assert f"VENV_PROFILE={profile}" in log_content
            assert f"VENV_UV_BIN={short_zb}/bin/uv" in log_content
    finally:
        shutil.rmtree(str(short_zb), ignore_errors=True)
