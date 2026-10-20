from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


# The installer renders plists with /usr/libexec/PlistBuddy, which only exists on
# macOS. Guard on the binary rather than sys.platform so the reason names the
# actual missing dependency, matching tests/test_install_omp_extensions_local.py.
requires_launchd_plist_tooling = pytest.mark.skipif(
    not Path("/usr/libexec/PlistBuddy").exists(),
    reason="/usr/libexec/PlistBuddy is macOS-only",
)


def test_devspace_launchd_templates_define_two_user_agents():
    devspace = read("launchd/io.local.mac-bootstrap.devspace.plist")
    tunnel = read("launchd/io.local.mac-bootstrap.devspace-tunnel.plist")

    assert "<string>io.local.mac-bootstrap.devspace</string>" in devspace
    assert "<string>{{BOOTSTRAP}}/scripts/devspace-supervisor.sh</string>" in devspace
    assert "<key>RunAtLoad</key>" in devspace
    assert "<key>KeepAlive</key>" in devspace
    assert "{{LOG_DIR}}/launchd-devspace.stdout.log" in devspace
    assert "{{LOG_DIR}}/launchd-devspace.stderr.log" in devspace

    assert "<string>io.local.mac-bootstrap.devspace-tunnel</string>" in tunnel
    assert "<string>{{BOOTSTRAP}}/scripts/devspace-tunnel-supervisor.sh</string>" in tunnel
    assert "<key>RunAtLoad</key>" in tunnel
    assert "<key>KeepAlive</key>" in tunnel
    assert "{{LOG_DIR}}/launchd-tunnel.stdout.log" in tunnel
    assert "{{LOG_DIR}}/launchd-tunnel.stderr.log" in tunnel


def test_devspace_supervisor_contract():
    content = read("scripts/devspace-supervisor.sh")

    assert "./scripts/devspace-local.sh check" in content
    assert "./scripts/devspace-local.sh run" in content
    assert 'HEALTHY_CODES="200 400 401 405"' in content
    assert "STARTUP_TIMEOUT_SECONDS=180" in content
    assert "CHECK_INTERVAL_SECONDS=30" in content
    assert "MAX_FAILURES=3" in content
    assert 'export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"' in content
    assert "trap terminate TERM INT" in content


def test_devspace_tunnel_supervisor_contract():
    content = read("scripts/devspace-tunnel-supervisor.sh")

    assert "./scripts/devspace-local.sh --dry-run tunnel-run" in content
    assert "./scripts/devspace-local.sh tunnel-run" in content
    assert "<redacted>" in content
    assert 'export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"' in content
    assert 'export PATH="$HOME/.local/bin:/opt/homebrew/opt/node@22/bin' not in content
    assert "cloudflare_tunnel_token" not in content


def test_devspace_tunnel_supervisor_has_public_health_watchdog():
    """cloudflared gets stuck retrying a stale edge while the network is fine;
    the supervisor must probe the public endpoint and exit so launchd restarts
    it. Regression guard for 2026-08-24 hours-long 530 outage."""
    content = read("scripts/devspace-tunnel-supervisor.sh")

    assert "./scripts/devspace-local.sh public-url" in content
    assert "TUNNEL_CHECK_INTERVAL_SECONDS" in content
    assert "TUNNEL_MAX_FAILURES" in content
    assert "200|401|405" in content
    assert "consecutive public probe failures" in content
    assert '--noproxy "localhost,127.0.0.1,::1"' in content


def test_devspace_agent_installer_contract():
    content = read("scripts/install-devspace-agents.sh")

    assert "io.local.mac-bootstrap.devspace" in content
    assert "io.local.mac-bootstrap.devspace-tunnel" in content
    assert "bootstrap" in content
    assert "bootout" in content
    assert "kickstart -k" in content
    assert "devspace-local.sh print-config" in content
    assert "devspace-local.sh doctor" in content
    assert "launchd-devspace.stdout.log" in content
    assert "launchd-tunnel.stderr.log" in content
    assert 'PYTHON="${PYTHON:-$BOOTSTRAP/.venv/bin/python}"' in content
    assert 'PYTHON="$(command -v python3)"' in content
    assert "cloudflare_tunnel_token" not in content
    assert "--token" not in content


def test_makefiles_expose_devspace_agent_targets():
    template_makefile = read("Makefile")

    for target in (
        "devspace-install-agent",
        "devspace-unload-agent",
        "devspace-status",
        "devspace-logs",
        "devspace-restart",
    ):
        assert f"{target}:" in template_makefile

    root_makefile = ROOT.parent / "Makefile"
    if root_makefile.is_file():
        content = root_makefile.read_text(encoding="utf-8")
        for target in (
            "devspace-install-agent",
            "devspace-unload-agent",
            "devspace-status",
            "devspace-logs",
            "devspace-restart",
        ):
            assert f"{target}:" in content

    assert "$(MAKE) syntax-check" in template_makefile


def test_tunnel_run_forces_http2_protocol():
    """cloudflared must pin --protocol http2: through a local TUN proxy the
    default QUIC transport flaps (edge dials time out / TLS EOF) and the
    public URL returns 530. Regression guard for 2026-08-24 outage."""
    content = read("scripts/devspace_local.py")
    assert '"--protocol", "http2"' in content


def _maintenance_agent_fixture(tmp_path):
    import shutil

    bootstrap = tmp_path / "bootstrap & | ' \\ checkout"
    shutil.copytree(ROOT / "launchd", bootstrap / "launchd")
    scripts = bootstrap / "scripts"
    scripts.mkdir()
    for name in (
        "install-maintenance-agents.sh",
        "claude-daemon.sh",
        "clean-cache.sh",
        "organize-downloads.sh",
    ):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)

    launch_agents = tmp_path / "home/Library/LaunchAgents"
    launch_agents.mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    return scripts, launch_agents, fake_bin


@requires_launchd_plist_tooling
def test_maintenance_agent_renderer_expands_paths_for_every_task(tmp_path):
    import os
    import subprocess

    scripts, launch_agents, fake_bin = _maintenance_agent_fixture(tmp_path)
    calls = fake_bin / "launchctl-calls"
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$LAUNCHCTL_CALLS\"\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LAUNCHCTL_CALLS": str(calls),
    }
    subprocess.run(
        [str(scripts / "install-maintenance-agents.sh"), "install"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )

    expected = {
        "claude-daemon": "claude-daemon.sh",
        "cache-cleanup": "clean-cache.sh",
        "downloads-organizer": "organize-downloads.sh",
        "system-patrol": "system-patrol.sh",
    }
    for name, script in expected.items():
        plist = launch_agents / f"io.local.mac-bootstrap.{name}.plist"
        result = subprocess.run(
            ["/usr/libexec/PlistBuddy", "-c", "Print :ProgramArguments:1", str(plist)],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == str(scripts / script)
        assert "{{BOOTSTRAP}}" not in plist.read_text(encoding="utf-8")

    calls_text = calls.read_text(encoding="utf-8")
    assert calls_text.count("bootout gui/") == 4
    assert calls_text.count("bootstrap gui/") == 4


@requires_launchd_plist_tooling
def test_maintenance_agent_renderer_cleans_temp_plist_on_validation_failure(tmp_path):
    import os
    import subprocess

    scripts, launch_agents, fake_bin = _maintenance_agent_fixture(tmp_path)
    (fake_bin / "plutil").write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
    (fake_bin / "plutil").chmod(0o755)
    calls = fake_bin / "launchctl-calls"
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$LAUNCHCTL_CALLS\"\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LAUNCHCTL_CALLS": str(calls),
    }
    result = subprocess.run(
        [str(scripts / "install-maintenance-agents.sh"), "install", "cache-cleanup"],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 9
    assert list(launch_agents.iterdir()) == []
    assert not calls.exists()


@requires_launchd_plist_tooling
def test_maintenance_agent_renderer_restores_previous_plist_on_bootstrap_failure(
    tmp_path,
):
    import os
    import shutil
    import subprocess

    scripts, launch_agents, fake_bin = _maintenance_agent_fixture(tmp_path)
    target = launch_agents / "io.local.mac-bootstrap.cache-cleanup.plist"
    shutil.copy2(ROOT / "launchd" / target.name, target)
    previous_script = "/previous/bootstrap/scripts/clean-cache.sh"
    subprocess.run(
        [
            "/usr/libexec/PlistBuddy",
            "-c",
            f"Set :ProgramArguments:1 '{previous_script}'",
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    calls = fake_bin / "launchctl-calls"
    failed_once = fake_bin / "failed-bootstrap"
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$LAUNCHCTL_CALLS\"\n"
        "if [ \"$1\" = bootstrap ] && [ ! -f \"$FAILED_ONCE\" ]; then\n"
        "  : > \"$FAILED_ONCE\"\n"
        "  exit 17\n"
        "fi\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LAUNCHCTL_CALLS": str(calls),
        "FAILED_ONCE": str(failed_once),
    }
    result = subprocess.run(
        [str(scripts / "install-maintenance-agents.sh"), "install", "cache-cleanup"],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 17
    restored = subprocess.run(
        ["/usr/libexec/PlistBuddy", "-c", "Print :ProgramArguments:1", str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert restored.stdout.strip() == previous_script
    calls_text = calls.read_text(encoding="utf-8")
    assert calls_text.count("bootout gui/") == 2
    assert calls_text.count("bootstrap gui/") == 2
    assert list(launch_agents.iterdir()) == [target]


@requires_launchd_plist_tooling
def test_maintenance_agent_renderer_removes_new_plist_on_bootstrap_failure(tmp_path):
    import os
    import subprocess

    scripts, launch_agents, fake_bin = _maintenance_agent_fixture(tmp_path)
    target = launch_agents / "io.local.mac-bootstrap.cache-cleanup.plist"
    calls = fake_bin / "launchctl-calls"
    failed_once = fake_bin / "failed-bootstrap"
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$LAUNCHCTL_CALLS\"\n"
        "if [ \"$1\" = bootstrap ] && [ ! -f \"$FAILED_ONCE\" ]; then\n"
        "  : > \"$FAILED_ONCE\"\n"
        "  exit 17\n"
        "fi\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LAUNCHCTL_CALLS": str(calls),
        "FAILED_ONCE": str(failed_once),
    }
    result = subprocess.run(
        [str(scripts / "install-maintenance-agents.sh"), "install", "cache-cleanup"],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 17
    assert not target.exists()
    calls_text = calls.read_text(encoding="utf-8")
    assert calls_text.count("bootout gui/") == 2
    assert calls_text.count("bootstrap gui/") == 1
    assert calls_text.count("disable gui/") == 1
    assert list(launch_agents.iterdir()) == []
