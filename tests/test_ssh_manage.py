"""Tests for SSH deploy and verification workflow."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ssh-manage.sh"


def run_ssh_manage(tmp_home: Path, private_dir: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_home)
    env["MAC_BOOTSTRAP_PRIVATE_DIR"] = str(private_dir)
    return subprocess.run(
        [str(SCRIPT), *args],
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


@pytest.mark.skipif(shutil.which("ssh") is None, reason="ssh not installed")
def test_install_and_verify_are_idempotent_with_legacy_private_key_layout(tmp_path: Path) -> None:
    home = tmp_path / "home"
    private = tmp_path / "private"
    shell_dir = private / "shell"
    config_dir = shell_dir / "ssh_config.d"
    home.mkdir()
    config_dir.mkdir(parents=True)

    key_path = shell_dir / "cc15_rsa"
    key_path.write_text(
        "fake ssh key payload\n"
    )
    key_path.chmod(0o644)

    config_path = config_dir / "cc15"
    config_path.write_text(
        "Host cc15\n"
        "  HostName localhost\n"
        "  User root\n"
        "  Port 22\n"
        "  IdentityFile ~/.ssh/keys/cc15_rsa\n"
        "  IdentitiesOnly yes\n"
        "  StrictHostKeyChecking no\n"
    )
    (home / ".ssh").mkdir()
    (home / ".ssh" / "known_hosts.old").write_text("stale\n")
    (home / ".ssh" / "legacy.corrupt.1").write_text("stale\n")

    first = run_ssh_manage(home, private, "install")
    assert first.returncode == 0, first.stderr
    second = run_ssh_manage(home, private, "install")
    assert second.returncode == 0, second.stderr

    ssh_config = home / ".ssh" / "config"
    assert ssh_config.is_symlink()
    assert ssh_config.resolve() == (SCRIPT.parent.parent / "shell" / "ssh_config")
    assert ssh_config.read_text().splitlines().count("Include ~/.ssh/config.d/*") == 1

    deployed_config = home / ".ssh" / "config.d" / "cc15"
    assert deployed_config.is_symlink()
    assert deployed_config.resolve() == config_path

    deployed_key = home / ".ssh" / "cc15_rsa"
    deployed_key = home / ".ssh" / "keys" / "cc15_rsa"
    assert deployed_key.is_symlink()
    assert deployed_key.resolve() == key_path
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert not (home / ".ssh" / "known_hosts.old").exists()
    assert not (home / ".ssh" / "legacy.corrupt.1").exists()
    assert not (home / ".ssh" / "cc15_rsa").exists()

    verify = run_ssh_manage(home, private, "verify")
    assert verify.returncode == 0, verify.stderr
    assert "SSH verify ok" in verify.stdout


def test_add_key_from_stdin_creates_private_key_and_host_snippet(tmp_path: Path) -> None:
    home = tmp_path / "home"
    private = tmp_path / "private"
    shell_dir = private / "shell"
    home.mkdir()
    shell_dir.mkdir(parents=True)

    result = run_ssh_manage(
        home,
        private,
        "add-key",
        "--name",
        "stdin_key",
        "--stdin",
        "--host",
        "example-host",
        "--hostname",
        "example.com",
        "--user",
        "alice",
        input_text="stdin ssh key payload\n",
    )
    assert result.returncode == 0, result.stderr

    key_path = shell_dir / "ssh_keys" / "stdin_key"
    assert key_path.exists()
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600

    config_path = shell_dir / "ssh_config.d" / "example-host"
    assert config_path.exists()
    assert "IdentityFile ~/.ssh/keys/stdin_key" in config_path.read_text()


def test_verify_rejects_unmanaged_top_level_ssh_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    private = tmp_path / "private"
    shell_dir = private / "shell"
    config_dir = shell_dir / "ssh_config.d"
    keys_dir = shell_dir / "ssh_keys"
    home.mkdir()
    config_dir.mkdir(parents=True)
    keys_dir.mkdir(parents=True)

    (shell_dir / "ssh_config").write_text("Include ~/.ssh/config.d/*\n")
    (config_dir / "host").write_text(
        "Host host\n"
        "  HostName localhost\n"
        "  User root\n"
        "  IdentityFile ~/.ssh/keys/test_key\n"
    )
    (keys_dir / "test_key").write_text("private\n")

    install = run_ssh_manage(home, private, "install")
    assert install.returncode == 0, install.stderr

    rogue = home / ".ssh" / "rogue.txt"
    rogue.write_text("bad\n")

    verify = run_ssh_manage(home, private, "verify")
    assert verify.returncode != 0
    assert "unexpected ~/.ssh entry" in verify.stderr


@pytest.mark.skipif(shutil.which("ssh") is None, reason="ssh not installed")
def test_dsliam_legacy_host_overrides_survive_global_defaults(tmp_path: Path) -> None:
    home = tmp_path / "home"
    private = tmp_path / "private"
    shell_dir = private / "shell"
    config_dir = shell_dir / "ssh_config.d"
    keys_dir = shell_dir / "ssh_keys"
    home.mkdir()
    config_dir.mkdir(parents=True)
    keys_dir.mkdir(parents=True)

    (shell_dir / "ssh_config").write_text(
        "Include ~/.ssh/config.d/*\n"
        "Host *\n"
        "  ServerAliveInterval 30\n"
        "  ServerAliveCountMax 5\n"
        "  TCPKeepAlive no\n"
        "  ConnectTimeout 5\n"
        "  ConnectionAttempts 2\n"
        "  ControlMaster auto\n"
        "  ControlPath ~/.ssh/cm-%C\n"
        "  ControlPersist 10m\n"
    )
    (config_dir / "dsliam").write_text(
        "Host dsliam\n"
        "  HostName dsliam.example.com\n"
        "  User legacy\n"
        "  Port 22\n"
        "  IdentityFile ~/.ssh/keys/id_rsa_dsliam\n"
        "  IdentitiesOnly yes\n"
        "  ProxyCommand ~/.ssh/connect-proxy.py %h %p\n"
        "  SetEnv TERM=xterm-256color\n"
        "  KbdInteractiveAuthentication yes\n"
        "  NumberOfPasswordPrompts 1\n"
        "  HostKeyAlgorithms +ssh-rsa\n"
        "  PubkeyAcceptedAlgorithms +ssh-rsa\n"
        "  KexAlgorithms +diffie-hellman-group1-sha1\n"
        "  Ciphers +aes128-cbc\n"
        "  MACs +hmac-sha1\n"
        "  ServerAliveInterval 60\n"
        "  ServerAliveCountMax 10\n"
        "  ControlMaster no\n"
        "  ControlPath none\n"
        "  ControlPersist no\n"
        "\n"
        "Host dsliam-mux\n"
        "  HostName dsliam.example.com\n"
        "  User legacy\n"
        "  Port 22\n"
        "  IdentityFile ~/.ssh/keys/id_rsa_dsliam\n"
        "  IdentitiesOnly yes\n"
        "  ProxyCommand ~/.ssh/connect-proxy.py %h %p\n"
        "  SetEnv TERM=xterm-256color\n"
        "  KbdInteractiveAuthentication yes\n"
        "  NumberOfPasswordPrompts 1\n"
        "  HostKeyAlgorithms +ssh-rsa\n"
        "  PubkeyAcceptedAlgorithms +ssh-rsa\n"
        "  KexAlgorithms +diffie-hellman-group1-sha1\n"
        "  Ciphers +aes128-cbc\n"
        "  MACs +hmac-sha1\n"
        "  ServerAliveInterval 60\n"
        "  ServerAliveCountMax 10\n"
        "  ControlMaster auto\n"
        "  ControlPath ~/.ssh/cm-%r@%h:%p\n"
        "  ControlPersist 8h\n"
    )
    (keys_dir / "id_rsa_dsliam").write_text("legacy key\n")

    install = run_ssh_manage(home, private, "install")
    assert install.returncode == 0, install.stderr

    env = os.environ.copy()
    env["HOME"] = str(home)
    dsliam = subprocess.run(
        ["ssh", "-G", "dsliam"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert dsliam.returncode == 0, dsliam.stderr
    dsliam_out = dsliam.stdout
    assert "controlmaster false" in dsliam_out
    assert "controlpersist no" in dsliam_out
    assert "serveraliveinterval 60" in dsliam_out
    assert "serveralivecountmax 10" in dsliam_out
    assert "identityfile ~/.ssh/keys/id_rsa_dsliam" in dsliam_out
    assert "proxycommand ~/.ssh/connect-proxy.py %h %p" in dsliam_out

    dsliam_mux = subprocess.run(
        ["ssh", "-G", "dsliam-mux"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert dsliam_mux.returncode == 0, dsliam_mux.stderr
    mux_out = dsliam_mux.stdout
    assert "controlmaster auto" in mux_out
    assert "controlpersist 28800" in mux_out
    assert "controlpath " in mux_out
    assert "identityfile ~/.ssh/keys/id_rsa_dsliam" in mux_out
