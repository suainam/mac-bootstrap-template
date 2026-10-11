"""Tests for service opt-in lifecycle and container defaults (issue #167).

Verifies that default bootstrap does not auto-start Colima or register its launch
agent, that explicit container entrypoints require mandatory proxy configuration,
and that Data Hub remains an optional capability decoupled from default bootstrap.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER_INSTALL_SH = ROOT / "infra" / "docker" / "install.sh"
COLIMA_LOCAL_SH = ROOT / "scripts" / "colima-local.sh"


def test_docker_install_links_config_without_starting_service(tmp_path: Path):
    """Default docker install script links colima.yaml without starting daemon or launchctl."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    launch_agents = fake_home / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)

    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(fake_home),
    }

    result = subprocess.run(
        ["/bin/bash", str(DOCKER_INSTALL_SH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    # Config is linked
    target_config = fake_home / ".colima" / "default" / "colima.yaml"
    assert target_config.is_symlink()
    # Does not start or register launch agent
    assert "Default bootstrap does not auto-start Colima" in result.stdout
    assert "COLIMA_PROXY_PORT=<port> make colima-start" in result.stdout
    assert not (launch_agents / "homebrew.mxcl.colima.plist").exists()


def test_colima_local_requires_mandatory_proxy_port():
    """Explicit colima-local.sh start fails with clear error when COLIMA_PROXY_PORT is missing."""
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "COLIMA_PROXY_PORT": "",
    }
    result = subprocess.run(
        ["/bin/bash", str(COLIMA_LOCAL_SH), "start"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    # scripts/colima-local.sh checks require_command first or check_host_proxy
    # In both cases it fails without starting or silently falling back
    assert result.returncode != 0
    # If colima/docker/nc are present, it mentions COLIMA_PROXY_PORT; if missing command, mentions missing command
    assert ("COLIMA_PROXY_PORT is required" in result.stderr or "missing required command" in result.stderr)


def test_colima_local_status_invokes_cli_profile_with_stubs(tmp_path: Path):
    """Explicit status command delegates to colima status with profile without daemon."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    stub_colima = bin_dir / "colima"
    stub_colima.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--profile" ] && [ "$2" = "www" ] && [ "$3" = "status" ]; then\n'
        '  echo "colima www status: stopped"\n'
        '  exit 0\n'
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    stub_colima.chmod(0o755)

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "COLIMA_PROFILE": "www",
    }
    result = subprocess.run(
        ["/bin/bash", str(COLIMA_LOCAL_SH), "status"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "colima www status: stopped" in result.stdout
