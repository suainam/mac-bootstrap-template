"""Local CLI, app, font, and Brewfile inventory checks."""

import json
import os
from pathlib import Path

import pytest

from helpers import TEMPLATE, brew_skip_tokens, declared_brew_formulas, run


pytestmark = pytest.mark.machine


# ── Brewfile formula inventory ───────────────────────────────────────

def test_declared_brew_formulas_are_installed():
    """The active Brewfile declarations are installed in their authoritative manager."""
    out, err, rc = run("brew list --formula")
    assert rc == 0, f"brew formula inventory failed: {err}"
    brew_installed = set(out.splitlines())

    out, err, rc = run('zb --root "${ZEROBREW_ROOT:-/opt/zerobrew}" list')
    assert rc == 0, f"zerobrew formula inventory failed: {err}"
    zb_installed = {line.split()[0] for line in out.splitlines() if line}

    ownership = json.loads((Path(TEMPLATE) / "scripts" / "package-ownership.json").read_text())
    zb_manifest = set(ownership["zerobrew_formulas"])

    active = declared_brew_formulas() - brew_skip_tokens()
    missing = sorted(active - (brew_installed | zb_installed))
    assert not missing, f"Brewfile formulae not installed: {', '.join(missing)}"

    duplicates = sorted(active & brew_installed & zb_installed)
    assert not duplicates, f"Brewfile formulae duplicated across brew and zb: {', '.join(duplicates)}"

    wrong_zb = sorted((active & zb_manifest) - zb_installed)
    assert not wrong_zb, f"Zerobrew-owned formulae not in zb: {', '.join(wrong_zb)}"

    wrong_brew = sorted((active - zb_manifest) - brew_installed)
    assert not wrong_brew, f"Homebrew-owned formulae not in brew: {', '.join(wrong_brew)}"

# ── GUI apps ──────────────────────────────────────────────────────────

GUI_APPS = {
    "Ghostty": ("/Applications/Ghostty.app", "ghostty"),
    "Hammerspoon": ("/Applications/Hammerspoon.app", "hammerspoon"),
}


@pytest.mark.parametrize("name,entry", GUI_APPS.items(), ids=list(GUI_APPS.keys()))
def test_gui_app_installed(name, entry):
    path, token = entry
    if token in brew_skip_tokens():
        pytest.skip(f"{name} opted out via Homebrew Bundle")
    assert os.path.isdir(path), f"{name} not found at {path}"

# ── Font ──────────────────────────────────────────────────────────────

def test_font_installed():
    font = os.path.expanduser("~/Library/Fonts/LigaSFMonoNerdFont-Regular.otf")
    assert os.path.exists(font), "LigaSFMono Nerd Font not found"


def test_brewfile_has_liga_sfmono_font():
    content = open(os.path.join(TEMPLATE, "Brewfile")).read()
    assert 'cask "font-sf-mono-nerd-font-ligaturized"' in content

# ── Brewfile ──────────────────────────────────────────────────────────

def test_brewfile_has_ghostty():
    content = open(os.path.join(TEMPLATE, "Brewfile")).read()
    assert 'cask "ghostty"' in content


def test_brewfile_has_eza():
    content = open(os.path.join(TEMPLATE, "Brewfile")).read()
    assert 'brew "eza"' in content


def test_brewfile_has_bat():
    content = open(os.path.join(TEMPLATE, "Brewfile")).read()
    assert 'brew "bat"' in content


def test_brewfile_has_codex_threadripper():
    content = open(os.path.join(TEMPLATE, "Brewfile")).read()
    assert 'tap "wangnov/tap"' in content
    assert 'brew "codex-threadripper"' in content
