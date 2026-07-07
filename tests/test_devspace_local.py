from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import signal
import sys


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, rel_path: str):
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


devspace_local = load_module("devspace_local", "scripts/devspace_local.py")


def test_load_devspace_config_expands_home_and_validates_allowed_roots(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    private_dir = repo / "private" / "agent"
    allowed = repo / "allowed"
    allowed.mkdir(parents=True)
    private_dir.mkdir(parents=True)
    runtime = private_dir / "devspace.runtime.jsonc"
    runtime.write_text(
        """{
          // comment
          "paths": {"allowed_roots": ["$HOME/repo/allowed"]},
          "server": {"host": "127.0.0.1", "port": 7676},
          "runtime": {"log_dir": "$HOME/repo/private/agent/logs/devspace"}
        }""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))

    cfg = devspace_local.load_devspace_config(repo_root=repo, config_path=runtime)

    assert cfg.allowed_roots == [allowed]
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 7676
    assert cfg.log_dir == repo / "private" / "agent" / "logs" / "devspace"
    assert devspace_local.validate_config(cfg) == []


def test_validate_config_reports_missing_allowed_root_and_bad_port(tmp_path):
    cfg = devspace_local.DevSpaceConfig(
        source_path=tmp_path / "private/agent/devspace.runtime.jsonc",
        allowed_roots=[tmp_path / "missing"],
        host="127.0.0.1",
        port=99999,
        public_base_url="http://example.com/mcp",
        cloudflare_tunnel_token="",
        node_preference="auto",
        install_mode="brew+npm",
        devspace_bin="",
        npm_bin="",
        log_dir=tmp_path / "logs/devspace",
    )

    errors = devspace_local.validate_config(cfg)

    assert "paths.allowed_roots[0] does not exist" in errors
    assert "server.port must be between 1 and 65535" in errors
    assert "exposure.public_base_url must start with https://" in errors


def test_resolve_binaries_prefers_explicit_overrides(tmp_path):
    cfg = devspace_local.DevSpaceConfig(
        source_path=tmp_path / "private/agent/devspace.runtime.jsonc",
        allowed_roots=[tmp_path],
        host="127.0.0.1",
        port=7676,
        public_base_url="",
        cloudflare_tunnel_token="",
        node_preference="auto",
        install_mode="brew+npm",
        devspace_bin="/custom/bin/devspace",
        npm_bin="/custom/bin/npm",
        log_dir=tmp_path / "logs/devspace",
    )

    bins = devspace_local.resolve_binaries(cfg, env={"PATH": ""})

    assert bins.devspace == "/custom/bin/devspace"
    assert bins.npm == "/custom/bin/npm"


def test_build_install_commands_adds_brew_and_npm_when_missing(tmp_path):
    cfg = devspace_local.DevSpaceConfig(
        source_path=tmp_path / "private/agent/devspace.runtime.jsonc",
        allowed_roots=[tmp_path],
        host="127.0.0.1",
        port=7676,
        public_base_url="",
        cloudflare_tunnel_token="",
        node_preference="auto",
        install_mode="brew+npm",
        devspace_bin="",
        npm_bin="",
        log_dir=tmp_path / "logs/devspace",
    )
    bins = devspace_local.ResolvedBinaries(node="", npm="", devspace="", brew="/opt/homebrew/bin/brew")

    commands = devspace_local.build_install_commands(cfg, bins)

    assert commands == [
        ["/opt/homebrew/bin/brew", "install", "node@22"],
        ["/opt/homebrew/bin/brew", "link", "--overwrite", "--force", "node@22"],
        ["npm", "install", "-g", "@waishnav/devspace"],
    ]


def test_shell_wrapper_calls_python_helper():
    content = (ROOT / "scripts/devspace-local.sh").read_text(encoding="utf-8")
    assert "devspace_local.py" in content
    assert '"$PYTHON" "$SCRIPT_DIR/devspace_local.py" "$@"' in content


def test_build_run_command_includes_allowed_roots_and_port(tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    cfg = devspace_local.DevSpaceConfig(
        source_path=tmp_path / "private/agent/devspace.runtime.jsonc",
        allowed_roots=[repo_a, repo_b],
        host="127.0.0.1",
        port=7676,
        public_base_url="https://devspace.example.com",
        cloudflare_tunnel_token="fake-token",
        node_preference="auto",
        install_mode="brew+npm",
        devspace_bin="",
        npm_bin="",
        log_dir=tmp_path / "logs/devspace",
    )
    bins = devspace_local.ResolvedBinaries(
        node="/opt/homebrew/bin/node",
        npm="/opt/homebrew/bin/npm",
        devspace="/opt/homebrew/bin/devspace",
        brew="/opt/homebrew/bin/brew",
    )

    command = devspace_local.build_run_command(cfg, bins)
    run_env = devspace_local.build_run_env(cfg, env={})

    assert command == ["/opt/homebrew/bin/devspace", "serve"]
    assert run_env["HOST"] == "127.0.0.1"
    assert run_env["PORT"] == "7676"
    assert run_env["DEVSPACE_ALLOWED_ROOTS"] == f"{repo_a},{repo_b}"
    assert run_env["DEVSPACE_PUBLIC_BASE_URL"] == "https://devspace.example.com"


def test_cmd_run_forwards_sigterm_to_devspace_child(monkeypatch, tmp_path):
    runtime = tmp_path / "private/agent/devspace.runtime.jsonc"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        json.dumps(
            {
                "paths": {"allowed_roots": [str(tmp_path)]},
                "server": {"host": "127.0.0.1", "port": 7676},
                "runtime": {
                    "devspace_bin": "/opt/homebrew/bin/devspace",
                    "log_dir": str(tmp_path / "logs/devspace"),
                },
            }
        ),
        encoding="utf-8",
    )
    registered: list[tuple[int, object]] = []

    class FakeProcess:
        returncode = None
        terminated = False
        killed = False

        def wait(self, timeout=None):
            if timeout == 10:
                self.returncode = -signal.SIGTERM
                return self.returncode
            return 0

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    process = FakeProcess()

    def fake_popen(command, stdout, stderr, env):  # noqa: ARG001
        assert command == ["/opt/homebrew/bin/devspace", "serve"]
        return process

    def fake_signal(signum, handler):
        registered.append((signum, handler))
        return signal.SIG_DFL

    monkeypatch.setattr(devspace_local, "resolve_binaries", lambda config: devspace_local.ResolvedBinaries("node", "npm", "/opt/homebrew/bin/devspace", "brew"))
    monkeypatch.setattr(devspace_local, "get_devspace_doctor_output", lambda devspace_bin: (0, "ok"))
    monkeypatch.setattr(devspace_local, "check_port_available", lambda host, port: (True, "available"))
    monkeypatch.setattr(devspace_local.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(devspace_local.signal, "signal", fake_signal)

    rc = devspace_local.main(["--repo-root", str(tmp_path), "--config", str(runtime), "run"])

    assert rc == 0
    sigterm_handlers = [handler for signum, handler in registered if signum == signal.SIGTERM]
    assert sigterm_handlers
    try:
        sigterm_handlers[0](signal.SIGTERM, None)
    except SystemExit as exc:
        assert exc.code == 128 + signal.SIGTERM
    assert process.terminated is True
    assert process.killed is False


def test_cmd_doctor_reports_port_conflict(monkeypatch, tmp_path, capsys):
    runtime = tmp_path / "private/agent/devspace.runtime.jsonc"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        json.dumps(
            {
                "paths": {"allowed_roots": [str(tmp_path)]},
                "server": {"host": "127.0.0.1", "port": 7676},
                "runtime": {"log_dir": str(tmp_path / "logs/devspace")},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(devspace_local, "check_port_available", lambda host, port: (False, "pid=1234"))
    monkeypatch.setattr(devspace_local, "probe_local_mcp", lambda host, port, timeout=2.0: (None, "not checked"))

    rc = devspace_local.main(["--repo-root", str(tmp_path), "--config", str(runtime), "doctor"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "RUNTIME CONFLICT" in out
    assert "pid=1234" in out


def test_validate_devspace_setup_reports_missing_init():
    output = """Config file: missing
Auth file: missing
Config status: DEVSPACE_OAUTH_OWNER_TOKEN is required for DevSpace OAuth. Run: devspace init"""

    errors = devspace_local.validate_devspace_setup(output)

    assert "devspace is not initialized; run `devspace init` or provide DEVSPACE_OAUTH_OWNER_TOKEN before `run`" in errors
    assert "~/.devspace/config.json is missing" in errors
    assert "~/.devspace/auth.json is missing" in errors


def test_devspace_example_config_targets_current_repo():
    example_path = ROOT / "agent" / "devspace.runtime.example.jsonc"
    example = example_path.read_text(encoding="utf-8")
    data = json.loads(devspace_local.strip_jsonc(example))

    assert data["paths"]["allowed_roots"] == ["$HOME/work/config/mac-bootstrap"]
    assert data["server"]["host"] == "127.0.0.1"
    assert data["server"]["port"] == 7676
    assert data["exposure"]["public_base_url"] == ""
    assert data["exposure"]["cloudflare_tunnel_token"] == ""
    assert data["runtime"]["install_mode"] == "brew+npm"


def test_print_config_redacts_cloudflare_tunnel_token(tmp_path, monkeypatch, capsys):
    runtime = tmp_path / "private/agent/devspace.runtime.jsonc"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        json.dumps(
            {
                "paths": {"allowed_roots": [str(tmp_path)]},
                "server": {"host": "127.0.0.1", "port": 7676},
                "exposure": {
                    "public_base_url": "https://devspace.example.com",
                    "cloudflare_tunnel_token": "secret-token",
                },
                "runtime": {"log_dir": str(tmp_path / "logs/devspace")},
            }
        ),
        encoding="utf-8",
    )

    rc = devspace_local.main(["--repo-root", str(tmp_path), "--config", str(runtime), "print-config"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "secret-token" not in out
    assert '"cloudflare_tunnel_token": "configured"' in out


def test_tunnel_run_prints_redacted_command(monkeypatch, tmp_path, capsys):
    runtime = tmp_path / "private/agent/devspace.runtime.jsonc"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        json.dumps(
            {
                "paths": {"allowed_roots": [str(tmp_path)]},
                "server": {"host": "127.0.0.1", "port": 7676},
                "exposure": {"cloudflare_tunnel_token": "secret-token"},
                "runtime": {"log_dir": str(tmp_path / "logs/devspace")},
            }
        ),
        encoding="utf-8",
    )

    rc = devspace_local.main(["--repo-root", str(tmp_path), "--config", str(runtime), "--dry-run", "tunnel-run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "secret-token" not in out
    assert "cloudflared tunnel run --token <redacted>" in out
