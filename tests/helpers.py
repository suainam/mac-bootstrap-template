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


def brew_bundle_env() -> dict[str, str]:
    env = os.environ.copy()
    template_path = Path(TEMPLATE)
    private_dir = env.get("HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR") or env.get("MAC_BOOTSTRAP_PRIVATE_DIR")
    if not private_dir:
        candidate = template_path.parent / "private"
        if candidate.is_dir():
            private_dir = str(candidate.resolve())
    profile = env.get("HOMEBREW_MAC_BOOTSTRAP_PROFILE") or env.get("MAC_BOOTSTRAP_PROFILE")
    if not profile:
        resolver = template_path / "scripts" / "resolve-profile.sh"
        if resolver.is_file() and os.access(resolver, os.X_OK):
            probe_env = env.copy()
            if private_dir:
                probe_env["MAC_BOOTSTRAP_PRIVATE_DIR"] = private_dir
            res = subprocess.run([str(resolver)], capture_output=True, text=True, check=False, env=probe_env)
            if res.returncode == 0 and res.stdout.strip():
                profile = res.stdout.strip()
    if private_dir:
        env["MAC_BOOTSTRAP_PRIVATE_DIR"] = private_dir
        env["HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR"] = private_dir
    if profile:
        env["MAC_BOOTSTRAP_PROFILE"] = profile
        env["HOMEBREW_MAC_BOOTSTRAP_PROFILE"] = profile
    return env


def declared_brew_formulas() -> set[str]:
    """Return active formula declarations evaluated by Homebrew Bundle."""
    brewfile = Path(TEMPLATE) / "Brewfile"
    res = subprocess.run(
        ["brew", "bundle", "list", f"--file={brewfile}", "--formula"],
        capture_output=True,
        text=True,
        check=False,
        env=brew_bundle_env(),
    )
    if res.returncode != 0:
        raise RuntimeError(f"brew bundle list failed: {(res.stderr or res.stdout).strip()}")
    return {line.strip().split("/")[-1] for line in res.stdout.splitlines() if line.strip()}

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
