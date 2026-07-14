from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest

from helpers import PYTHON


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "scripts" / "context7-mcp-bridge.py"


def make_fake_context7(directory: Path) -> Path:
    executable = directory / "context7-mcp"
    executable.write_text(
        "#!/bin/sh\n"
        "printf '%s' \"${CONTEXT7_API_KEY-}\" > \"$CAPTURE_ENV\"\n"
        "printf '%s' \"$*\" > \"$CAPTURE_ARGS\"\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def run_bridge(tmp_path: Path, config_text: str | None) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    private_dir = tmp_path / "private"
    if config_text is not None:
        config_path = private_dir / "agent" / "context7.runtime.jsonc"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(config_text, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_context7(bin_dir)
    capture_env = tmp_path / "captured-env"
    capture_args = tmp_path / "captured-args"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MAC_BOOTSTRAP_PRIVATE_DIR": str(private_dir),
        "CAPTURE_ENV": str(capture_env),
        "CAPTURE_ARGS": str(capture_args),
    }
    result = subprocess.run(
        [PYTHON, str(BRIDGE), "--probe"],
        capture_output=True,
        text=True,
        env=env,
    )
    return result, capture_env, capture_args


def test_bridge_injects_private_key_into_child_only(tmp_path: Path):
    result, capture_env, capture_args = run_bridge(
        tmp_path,
        "// private\n{\"api_key\": \"ctx-secret\"}\n",
    )
    assert result.returncode == 0, result.stderr
    assert capture_env.read_text(encoding="utf-8") == "ctx-secret"
    assert capture_args.read_text(encoding="utf-8") == "--probe"
    assert "ctx-secret" not in result.stdout + result.stderr


def test_bridge_tightens_tracked_private_config_permissions(tmp_path: Path):
    result, _, _ = run_bridge(tmp_path, '{"api_key": "ctx-secret"}')
    config_path = tmp_path / "private/agent/context7.runtime.jsonc"
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_bridge_validation_tightens_permissions_without_launching(tmp_path: Path):
    private_dir = tmp_path / "private"
    config_path = private_dir / "agent/context7.runtime.jsonc"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('{"api_key": "ctx-secret"}', encoding="utf-8")
    config_path.chmod(0o644)
    env = {**os.environ, "MAC_BOOTSTRAP_PRIVATE_DIR": str(private_dir)}

    result = subprocess.run(
        [PYTHON, str(BRIDGE), "--validate-private-config"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_bridge_runs_keyless_when_private_config_is_missing(tmp_path: Path):
    result, capture_env, _ = run_bridge(tmp_path, None)
    assert result.returncode == 0, result.stderr
    assert not capture_env.exists() or capture_env.read_text(encoding="utf-8") == ""


def test_bridge_runs_keyless_for_placeholder_private_key(tmp_path: Path):
    result, capture_env, _ = run_bridge(tmp_path, '{"api_key": "REPLACE_ME"}')
    assert result.returncode == 0, result.stderr
    assert not capture_env.exists() or capture_env.read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    "config_text",
    ['{"api_key": 42}', '{"api_key": "bad\\u0001secret"}', '{"api_key": "bad\\u0085secret"}'],
)
def test_bridge_rejects_unsafe_private_key(tmp_path: Path, config_text: str):
    result, capture_env, _ = run_bridge(tmp_path, config_text)
    assert result.returncode == 2
    assert "Context7 private config invalid" in result.stderr
    assert not capture_env.exists()


def test_bridge_rejects_malformed_private_config_without_echoing_value(tmp_path: Path):
    result, capture_env, _ = run_bridge(tmp_path, '{"api_key": "bad\nsecret"}')
    assert result.returncode == 2
    assert "Context7 private config invalid" in result.stderr
    assert "bad" not in result.stdout + result.stderr
    assert not capture_env.exists()
