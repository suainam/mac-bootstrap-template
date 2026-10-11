"""Tests for service opt-in lifecycle and container defaults (issue #167).

Verifies via command logs that default bootstrap performs no daemon starts or
LaunchAgent registrations, and that explicit colima starts enforce mandatory
proxy ports before transitioning service state.
"""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER_INSTALL_SH = ROOT / "infra" / "docker" / "install.sh"
COLIMA_LOCAL_SH = ROOT / "scripts" / "colima-local.sh"


def make_spy_tool(bin_dir: Path, name: str, log_file: Path, script_body: str = ""):
    tool = bin_dir / name
    body = (
        "#!/usr/bin/env bash\n"
        f"echo \"{name} $@\" >> \"{log_file}\"\n"
        f"{script_body}\n"
    )
    tool.write_text(body, encoding="utf-8")
    tool.chmod(0o755)
    return tool


def test_default_docker_install_does_not_start_colima_or_launchctl(tmp_path: Path):
    """Default docker install script links colima.yaml without calling colima or launchctl."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    spy_bin = tmp_path / "bin"
    spy_bin.mkdir()
    cmd_log = tmp_path / "commands.log"

    make_spy_tool(spy_bin, "colima", cmd_log, "exit 0")
    make_spy_tool(spy_bin, "launchctl", cmd_log, "exit 0")
    make_spy_tool(spy_bin, "docker", cmd_log, "exit 0")

    env = {
        "PATH": f"{spy_bin}:/usr/bin:/bin",
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
    # Config symlink is created
    target_config = fake_home / ".colima" / "default" / "colima.yaml"
    assert target_config.is_symlink()
    assert target_config.resolve() == (ROOT / "infra" / "docker" / "colima.yaml").resolve()

    # Neither colima nor launchctl was invoked
    logged_cmds = cmd_log.read_text(encoding="utf-8") if cmd_log.exists() else ""
    assert "colima" not in logged_cmds
    assert "launchctl" not in logged_cmds


def test_explicit_colima_start_fails_without_mandatory_proxy_port(tmp_path: Path):
    """Explicit colima start fails without COLIMA_PROXY_PORT and never invokes colima start."""
    spy_bin = tmp_path / "bin"
    spy_bin.mkdir()
    cmd_log = tmp_path / "commands.log"

    make_spy_tool(spy_bin, "colima", cmd_log, "exit 0")
    make_spy_tool(spy_bin, "docker", cmd_log, "exit 0")
    make_spy_tool(spy_bin, "nc", cmd_log, "exit 0")

    env = {
        "PATH": f"{spy_bin}:/usr/bin:/bin",
        "COLIMA_PROXY_PORT": "",
    }
    result = subprocess.run(
        ["/bin/bash", str(COLIMA_LOCAL_SH), "start"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    logged_cmds = cmd_log.read_text(encoding="utf-8") if cmd_log.exists() else ""
    assert "colima --profile www start" not in logged_cmds


def test_explicit_colima_start_with_mandatory_proxy_port_transitions(tmp_path: Path):
    """Explicit start invokes colima start with proxy and resource args when port is given."""
    spy_bin = tmp_path / "bin"
    spy_bin.mkdir()
    cmd_log = tmp_path / "commands.log"

    # colima: status -> return 1 (not running), start -> return 0
    colima_logic = """
    if [ "$1" = "--profile" ] && [ "$3" = "status" ]; then
      exit 1
    fi
    exit 0
    """
    make_spy_tool(spy_bin, "colima", cmd_log, colima_logic)
    make_spy_tool(spy_bin, "docker", cmd_log, "exit 0")
    make_spy_tool(spy_bin, "nc", cmd_log, "exit 0")

    env = {
        "PATH": f"{spy_bin}:/usr/bin:/bin",
        "COLIMA_PROXY_PORT": "7890",
    }
    result = subprocess.run(
        ["/bin/bash", str(COLIMA_LOCAL_SH), "start"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    logged_cmds = cmd_log.read_text(encoding="utf-8")
    assert "nc -z 127.0.0.1 7890" in logged_cmds
    assert "colima --profile www start" in logged_cmds
    assert "--env HTTP_PROXY=http://host.lima.internal:7890" in logged_cmds
    assert "--env HTTPS_PROXY=http://host.lima.internal:7890" in logged_cmds


def test_explicit_colima_stop_invokes_profile_stop(tmp_path: Path):
    """Explicit stop delegates to colima profile stop."""
    spy_bin = tmp_path / "bin"
    spy_bin.mkdir()
    cmd_log = tmp_path / "commands.log"

    make_spy_tool(spy_bin, "colima", cmd_log, "exit 0")

    env = {
        "PATH": f"{spy_bin}:/usr/bin:/bin",
    }
    result = subprocess.run(
        ["/bin/bash", str(COLIMA_LOCAL_SH), "stop"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    logged_cmds = cmd_log.read_text(encoding="utf-8")
    assert "colima --profile www stop" in logged_cmds
