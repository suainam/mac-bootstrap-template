"""Shared helpers for mac-bootstrap tests."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


HOME = os.path.expanduser("~")
TEMPLATE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_HUB = Path(TEMPLATE) / "data-hub"
AGENT_SKILLS = Path(TEMPLATE) / "agent-skills"
DOCTOR_MANIFEST = os.path.join(TEMPLATE, "scripts", "doctor-manifest.json")
PYTHON = sys.executable


def run(cmd: str) -> tuple[str, str, int]:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def tokens_split(text: str) -> list[str]:
    return [token for token in text.split() if token]


def declared_brew_formulas() -> set[str]:
    """Return active formula declarations; commented Brewfile lines are optional."""
    formulas: set[str] = set()
    for raw in (Path(TEMPLATE) / "Brewfile").read_text().splitlines():
        line = raw.strip()
        if line.startswith('brew "') and line.endswith('"'):
            name = line[len('brew "'):-1]
            # brew list --formula outputs the short name for tapped formulae (e.g. opencode-v2)
            formulas.add(name.split("/")[-1])
    return formulas


def brew_skip_tokens() -> set[str]:
    """Return native Homebrew Bundle opt-outs."""
    return set(tokens_split(
        os.environ.get("HOMEBREW_BUNDLE_BREW_SKIP", "") + " "
        + os.environ.get("HOMEBREW_BUNDLE_CASK_SKIP", "")
    ))

def require_tmux_live_socket() -> None:
    if "tmux" not in declared_brew_formulas():
        pytest.skip("tmux is optional and not declared in template/Brewfile")

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
    manifest = json.loads(Path(DOCTOR_MANIFEST).read_text())
    return manifest["managed_symlinks"]
