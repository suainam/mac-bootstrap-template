"""Behavior tests for Zerobrew -> Homebrew cutover migration (Issue #198)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = TEMPLATE / "scripts"
MIGRATE_SCRIPT = SCRIPTS_DIR / "migrate-to-homebrew.sh"


def test_cutover_verification_failure_blocks_uninstall(tmp_path: Path) -> None:
    """If a tool fails verification in Homebrew, its zb copy is NOT uninstalled."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    fake_zb = tmp_path / "zb_root"
    (fake_zb / "bin").mkdir(parents=True)
    (fake_zb / "bin" / "uv").write_text("#!/bin/sh\nexit 0\n")
    (fake_zb / "bin" / "uv").chmod(0o755)

    mock_brew_log = tmp_path / "brew.log"
    mock_brew = bin_dir / "brew"
    mock_brew.write_text(f"""#!/usr/bin/env bash
echo "brew $@" >> "{mock_brew_log}"
if [ "$1" = "bundle" ] && [ "$2" = "list" ]; then
    echo "uv"
    exit 0
fi
if [ "$1" = "list" ] && [ "$2" = "--formula" ]; then
    exit 0
fi
if [ "$1" = "install" ]; then
    # Fake install that produces a broken binary
    mkdir -p "{bin_dir}/../opt_homebrew/bin"
    echo '#!/bin/sh' > "{bin_dir}/../opt_homebrew/bin/uv"
    echo 'exit 1' >> "{bin_dir}/../opt_homebrew/bin/uv"
    chmod +x "{bin_dir}/../opt_homebrew/bin/uv"
    exit 0
fi
exit 0
""")
    mock_brew.chmod(0o755)

    mock_zb_log = tmp_path / "zb.log"
    mock_zb = bin_dir / "zb"
    mock_zb.write_text(f"""#!/usr/bin/env bash
echo "zb $@" >> "{mock_zb_log}"
if [ "$3" = "list" ]; then
    echo "uv 0.13.4"
    exit 0
fi
if [ "$3" = "uninstall" ] || [ "$5" = "uninstall" ]; then
    echo "zb uninstall $@" >> "{mock_zb_log}"
    exit 0
fi
exit 0
""")
    mock_zb.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["ZEROBREW_ROOT"] = str(fake_zb)
    env["ZEROBREW_PREFIX"] = str(fake_zb)
    env["HOMEBREW_PREFIX"] = str(tmp_path / "opt_homebrew")
    env["HOMEBREW_NO_AUTO_UPDATE"] = "1"
    (tmp_path / "opt_homebrew" / "bin").mkdir(parents=True)

    res = subprocess.run(
        [str(MIGRATE_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
    )

    # Verification must have failed, so zb uninstall uv must NOT be in zb log
    zb_log = mock_zb_log.read_text() if mock_zb_log.exists() else ""
    assert "uninstall uv" not in zb_log


def test_cutover_success_flow_verifies_and_relinks_docker_plugins(tmp_path: Path) -> None:
    """When Homebrew install succeeds and verifies, docker plugins are relinked and zb copy uninstalled."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    docker_plugins = fake_home / ".docker" / "cli-plugins"
    docker_plugins.mkdir(parents=True)

    fake_zb = tmp_path / "zb_root"
    (fake_zb / "bin").mkdir(parents=True)
    (fake_zb / "lib" / "docker" / "cli-plugins").mkdir(parents=True)
    (fake_zb / "bin" / "docker-compose").write_text("#!/bin/sh\nexit 0\n")
    (fake_zb / "bin" / "docker-compose").chmod(0o755)

    # Initial symlink pointing to zb
    (docker_plugins / "docker-compose").symlink_to(fake_zb / "lib" / "docker" / "cli-plugins" / "docker-compose")

    opt_homebrew = tmp_path / "opt_homebrew"
    hb_bin = opt_homebrew / "bin"
    hb_plugins = opt_homebrew / "lib" / "docker" / "cli-plugins"
    hb_bin.mkdir(parents=True)
    hb_plugins.mkdir(parents=True)

    mock_brew_log = tmp_path / "brew.log"
    mock_brew = bin_dir / "brew"
    mock_brew.write_text(f"""#!/usr/bin/env bash
echo "brew $@" >> "{mock_brew_log}"
if [ "$1" = "bundle" ] && [ "$2" = "list" ]; then
    echo "docker-compose"
    exit 0
fi
if [ "$1" = "list" ] && [ "$2" = "--formula" ]; then
    exit 0
fi
if [ "$1" = "install" ]; then
    # Fake successful install
    echo '#!/bin/sh' > "{hb_bin}/docker-compose"
    echo 'echo "Docker Compose version v2.29.0"' >> "{hb_bin}/docker-compose"
    chmod +x "{hb_bin}/docker-compose"
    echo '#!/bin/sh' > "{hb_plugins}/docker-compose"
    echo 'echo "Docker Compose version v2.29.0"' >> "{hb_plugins}/docker-compose"
    chmod +x "{hb_plugins}/docker-compose"
    exit 0
fi
exit 0
""")
    mock_brew.chmod(0o755)

    mock_zb_log = tmp_path / "zb.log"
    mock_zb = bin_dir / "zb"
    mock_zb.write_text(f"""#!/usr/bin/env bash
echo "zb $@" >> "{mock_zb_log}"
if [ "$3" = "list" ]; then
    echo "docker-compose 5.6.1"
    exit 0
fi
if [ "$5" = "uninstall" ]; then
    echo "zb uninstalled $6" >> "{mock_zb_log}"
    exit 0
fi
exit 0
""")
    mock_zb.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["DOCKER_CONFIG"] = str(fake_home / ".docker")
    env["ZEROBREW_ROOT"] = str(fake_zb)
    env["ZEROBREW_PREFIX"] = str(fake_zb)
    env["HOMEBREW_PREFIX"] = str(opt_homebrew)
    env["HOMEBREW_NO_AUTO_UPDATE"] = "1"

    res = subprocess.run(
        [str(MIGRATE_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0, f"stdout: {res.stdout}\nstderr: {res.stderr}"

    # Verify plugin relinked to Homebrew
    target = os.readlink(docker_plugins / "docker-compose")
    assert str(opt_homebrew) in target
    assert str(fake_zb) not in target

    # Verify zb uninstall was called
    zb_log = mock_zb_log.read_text()
    assert "zb uninstalled docker-compose" in zb_log


def test_cutover_repoints_rclone_webdav_plist(tmp_path: Path) -> None:
    """When rclone is verified, com.auroraops.rclone-webdav.plist is repointed to Homebrew."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    launch_agents = fake_home / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)

    plist_file = launch_agents / "com.auroraops.rclone-webdav.plist"
    plist_file.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/zerobrew/bin/rclone</string>
        <string>serve</string>
    </array>
</dict>
</plist>
""")

    fake_zb = tmp_path / "zb_root"
    (fake_zb / "bin").mkdir(parents=True)
    (fake_zb / "bin" / "rclone").write_text("#!/bin/sh\nexit 0\n")
    (fake_zb / "bin" / "rclone").chmod(0o755)

    opt_homebrew = tmp_path / "opt_homebrew"
    hb_bin = opt_homebrew / "bin"
    hb_bin.mkdir(parents=True)
    (hb_bin / "rclone").write_text("#!/bin/sh\necho 'rclone v1.75.2'\nexit 0\n")
    (hb_bin / "rclone").chmod(0o755)

    mock_brew = bin_dir / "brew"
    mock_brew.write_text("""#!/usr/bin/env bash
if [ "$1" = "list" ] && [ "$2" = "--formula" ]; then
    echo "rclone"
    exit 0
fi
exit 0
""")
    mock_brew.chmod(0o755)

    mock_zb = bin_dir / "zb"
    mock_zb.write_text("""#!/usr/bin/env bash
if [ "$3" = "list" ]; then
    echo "rclone 1.75.2"
    exit 0
fi
exit 0
""")
    mock_zb.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["ZEROBREW_ROOT"] = str(fake_zb)
    env["ZEROBREW_PREFIX"] = str(fake_zb)
    env["HOMEBREW_PREFIX"] = str(opt_homebrew)
    env["HOMEBREW_NO_AUTO_UPDATE"] = "1"

    res = subprocess.run(
        [str(MIGRATE_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0

    content = plist_file.read_text()
    assert f"{opt_homebrew}/bin/rclone" in content
    assert "/opt/zerobrew/bin/rclone" not in content


def test_cutover_candidate_calculation_respects_profile(tmp_path: Path) -> None:
    """Migration candidates evaluate active profile formulas without cross-pollinating."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    fake_zb = tmp_path / "zb_root"
    (fake_zb / "bin").mkdir(parents=True)

    mock_brew_log = tmp_path / "brew_calls.log"
    mock_brew = bin_dir / "brew"
    mock_brew.write_text(f"""#!/usr/bin/env bash
echo "brew $@" >> "{mock_brew_log}"
if [ "$1" = "bundle" ] && [ "$2" = "list" ]; then
    if [ "$MAC_BOOTSTRAP_PROFILE" = "work" ]; then
        echo "git"
        echo "tea"
        echo "lrzsz"
    else
        echo "git"
        echo "rclone"
        echo "rustic"
    fi
    exit 0
fi
if [ "$1" = "list" ] && [ "$2" = "--formula" ]; then
    echo "git"
    exit 0
fi
if [ "$1" = "install" ]; then
    exit 0
fi
exit 0
""")
    mock_brew.chmod(0o755)

    mock_zb = bin_dir / "zb"
    mock_zb.write_text("""#!/usr/bin/env bash
if [ "$3" = "list" ]; then
    exit 0
fi
exit 0
""")
    mock_zb.chmod(0o755)

    # Run for profile work
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["ZEROBREW_ROOT"] = str(fake_zb)
    env["ZEROBREW_PREFIX"] = str(fake_zb)
    env["HOMEBREW_PREFIX"] = str(tmp_path / "opt_homebrew")
    env["MAC_BOOTSTRAP_PROFILE"] = "work"
    env["HOMEBREW_NO_AUTO_UPDATE"] = "1"

    res = subprocess.run(
        [str(MIGRATE_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0

    calls = mock_brew_log.read_text()
    assert "tea" in calls
    assert "lrzsz" in calls
    assert "rclone" not in calls
    assert "rustic" not in calls


def _mock_cutover_env(tmp_path: Path, zb_listing: str, brew_listing: str = "") -> tuple[dict[str, str], Path, Path]:
    """Build a fake brew/zb environment; returns (env, docker_plugins_dir, zb_log)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    docker_plugins = fake_home / ".docker" / "cli-plugins"
    docker_plugins.mkdir(parents=True)

    fake_zb = tmp_path / "zb_root"
    (fake_zb / "bin").mkdir(parents=True)

    mock_brew = bin_dir / "brew"
    mock_brew.write_text(f"""#!/usr/bin/env bash
if [ "$1" = "bundle" ] && [ "$2" = "list" ]; then
    exit 0
fi
if [ "$1" = "list" ] && [ "$2" = "--formula" ]; then
    printf '%s' "{brew_listing}"
    exit 0
fi
exit 0
""")
    mock_brew.chmod(0o755)

    zb_log = tmp_path / "zb.log"
    mock_zb = bin_dir / "zb"
    mock_zb.write_text(f"""#!/usr/bin/env bash
echo "zb $@" >> "{zb_log}"
if [ "$3" = "list" ]; then
    printf '%s' "{zb_listing}"
    exit 0
fi
exit 0
""")
    mock_zb.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["DOCKER_CONFIG"] = str(fake_home / ".docker")
    env["ZEROBREW_ROOT"] = str(fake_zb)
    env["ZEROBREW_PREFIX"] = str(fake_zb)
    env["HOMEBREW_PREFIX"] = str(tmp_path / "opt_homebrew")
    env["HOMEBREW_NO_AUTO_UPDATE"] = "1"
    (tmp_path / "opt_homebrew" / "bin").mkdir(parents=True)
    return env, docker_plugins, zb_log


def test_cutover_unverified_replacement_keeps_docker_plugin_link(tmp_path: Path) -> None:
    """An unverified Homebrew replacement must not take over the docker plugin link."""
    env, docker_plugins, _ = _mock_cutover_env(tmp_path, "docker-compose 5.6.1\n")
    opt_homebrew = Path(env["HOMEBREW_PREFIX"])
    (opt_homebrew / "lib" / "docker" / "cli-plugins").mkdir(parents=True)
    # A binary exists but cannot run: verification fails.
    broken = opt_homebrew / "bin" / "docker-compose"
    broken.write_text("#!/bin/sh\nexit 1\n")
    broken.chmod(0o755)

    res = subprocess.run([str(MIGRATE_SCRIPT)], capture_output=True, text=True, env=env)

    assert res.returncode == 1, f"stdout: {res.stdout}\nstderr: {res.stderr}"
    assert not (docker_plugins / "docker-compose").exists()
    assert "unverified" in res.stderr


def test_cutover_unverified_replacement_keeps_launch_agent(tmp_path: Path) -> None:
    """An unverified rclone must not repoint the rclone-webdav LaunchAgent."""
    env, _, _ = _mock_cutover_env(tmp_path, "rclone 1.75.2\n")
    plist = Path(env["HOME"]) / "Library" / "LaunchAgents" / "com.auroraops.rclone-webdav.plist"
    plist.parent.mkdir(parents=True)
    original = "<string>/opt/zerobrew/bin/rclone</string>"
    plist.write_text(original)

    res = subprocess.run([str(MIGRATE_SCRIPT)], capture_output=True, text=True, env=env)

    assert res.returncode == 1, f"stdout: {res.stdout}\nstderr: {res.stderr}"
    assert plist.read_text() == original


def test_cutover_failed_zb_uninstall_fails_migration(tmp_path: Path) -> None:
    """A failed Zerobrew uninstall must not be reported as a completed migration."""
    env, _, zb_log = _mock_cutover_env(tmp_path, "uv 0.13.4\n", brew_listing="uv\n")
    uv = Path(env["HOMEBREW_PREFIX"]) / "bin" / "uv"
    uv.write_text("#!/bin/sh\necho 'uv 0.13.4'\n")
    uv.chmod(0o755)

    zb = Path(env["PATH"].split(os.pathsep)[0]) / "zb"
    zb.write_text(f"""#!/usr/bin/env bash
echo "zb $@" >> "{zb_log}"
if [ "$3" = "list" ]; then
    echo "uv 0.13.4"
    exit 0
fi
if [ "$3" = "uninstall" ] || [ "$5" = "uninstall" ]; then
    exit 1
fi
exit 0
""")
    zb.chmod(0o755)

    res = subprocess.run([str(MIGRATE_SCRIPT)], capture_output=True, text=True, env=env)

    assert res.returncode == 1, f"stdout: {res.stdout}\nstderr: {res.stderr}"
    assert "Migration Complete" not in res.stdout
    assert "remain installed in Zerobrew" in res.stderr


def test_cutover_rerun_relinks_plugin_already_absent_from_zerobrew(tmp_path: Path) -> None:
    """A rerun must still relink when Zerobrew no longer lists the tool."""
    env, docker_plugins, _ = _mock_cutover_env(tmp_path, "")
    opt_homebrew = Path(env["HOMEBREW_PREFIX"])
    plugins = opt_homebrew / "lib" / "docker" / "cli-plugins"
    plugins.mkdir(parents=True)
    plugin = plugins / "docker-compose"
    plugin.write_text("#!/bin/sh\necho 'Docker Compose version v5.6.1'\n")
    plugin.chmod(0o755)

    res = subprocess.run([str(MIGRATE_SCRIPT)], capture_output=True, text=True, env=env)

    assert res.returncode == 0, f"stdout: {res.stdout}\nstderr: {res.stderr}"
    assert os.readlink(docker_plugins / "docker-compose") == str(plugin)


def test_cutover_empty_zerobrew_inventory_is_not_a_formula(tmp_path: Path) -> None:
    """`zb list` prints a sentence when empty; it must not become a package name."""
    env, _, _ = _mock_cutover_env(tmp_path, "No formulas installed.\n")
    zb = Path(env["PATH"].split(os.pathsep)[0]) / "zb"
    zb.write_text("""#!/usr/bin/env bash
if [ "$3" = "list" ]; then
    echo "No formulas installed."
    exit 0
fi
exit 0
""")
    zb.chmod(0o755)

    res = subprocess.run([str(MIGRATE_SCRIPT)], capture_output=True, text=True, env=env)

    assert res.returncode == 0, f"stdout: {res.stdout}\nstderr: {res.stderr}"
    assert "Zerobrew kegs (0)" in res.stdout
    assert "Formulae needing Homebrew installation (0)" in res.stdout


def test_cutover_ignores_cellar_dirs_dropped_by_zb_database(tmp_path: Path) -> None:
    """A keg directory left behind after uninstall must not resurrect the package."""
    env, _, _ = _mock_cutover_env(tmp_path, "No formulas installed.\n")
    zb_root = Path(env["ZEROBREW_ROOT"])
    (zb_root / "db").mkdir(parents=True)
    import sqlite3

    with sqlite3.connect(zb_root / "db" / "zb.sqlite3") as db:
        db.execute("CREATE TABLE installed_kegs (name TEXT)")
    (zb_root / "Cellar" / "ast-grep" / "0.50.0").mkdir(parents=True)

    res = subprocess.run([str(MIGRATE_SCRIPT)], capture_output=True, text=True, env=env)

    assert res.returncode == 0, f"stdout: {res.stdout}\nstderr: {res.stderr}"
    assert "Zerobrew kegs (0)" in res.stdout
    assert "ast-grep" not in res.stdout.split("--- Step 1")[-1].split("--- Step 2")[0]
