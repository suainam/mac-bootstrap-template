"""Shared helpers for mac-bootstrap tests."""

import json
import os
import subprocess

import pytest


HOME = os.path.expanduser("~")
TEMPLATE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCTOR_MANIFEST = os.path.join(TEMPLATE, "scripts", "doctor-manifest.json")
PYTHON = os.path.join(TEMPLATE, ".venv", "bin", "python")


def run(cmd: str) -> tuple[str, str, int]:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def require_tmux_live_socket() -> None:
    _, err, rc = run("tmux show-option -g prefix")
    if rc == 0:
        return

    soft_fail_markers = (
        "Operation not permitted",
        "error connecting to /private/tmp/tmux-",
        "no server running",
        "failed to connect to server",
    )
    if any(marker in err for marker in soft_fail_markers):
        pytest.skip(f"tmux live socket unavailable: {err}")

    pytest.fail(f"tmux config error: {err}")


def managed_symlinks() -> dict[str, str]:
    manifest = json.loads(open(DOCTOR_MANIFEST).read())
    return manifest["managed_symlinks"]
