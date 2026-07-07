from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


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
    assert 'export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"' in content
    assert "trap terminate TERM INT" in content


def test_devspace_tunnel_supervisor_contract():
    content = read("scripts/devspace-tunnel-supervisor.sh")

    assert "./scripts/devspace-local.sh --dry-run tunnel-run" in content
    assert "./scripts/devspace-local.sh tunnel-run" in content
    assert "<redacted>" in content
    assert 'export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"' in content
    assert "cloudflare_tunnel_token" not in content


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
    root_makefile = (ROOT.parent / "Makefile").read_text(encoding="utf-8")

    for target in (
        "devspace-install-agent",
        "devspace-unload-agent",
        "devspace-status",
        "devspace-logs",
        "devspace-restart",
    ):
        assert f"{target}:" in template_makefile
        assert f"{target}:" in root_makefile

    assert "bash -n scripts/devspace-supervisor.sh" in template_makefile
    assert "bash -n scripts/devspace-tunnel-supervisor.sh" in template_makefile
    assert "bash -n scripts/install-devspace-agents.sh" in template_makefile
