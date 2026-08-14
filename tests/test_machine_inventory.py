"""Local CLI, app, font, and Brewfile inventory checks."""

import os

import pytest

from helpers import TEMPLATE, declared_brew_formulas, run


pytestmark = pytest.mark.machine


# ── Brewfile formula inventory ───────────────────────────────────────

def test_declared_brew_formulas_are_installed():
    """The active Brewfile declarations are the machine's required formula set."""
    out, err, rc = run("brew list --formula")
    assert rc == 0, f"brew formula inventory failed: {err}"

    installed = set(out.splitlines())
    missing = sorted(declared_brew_formulas() - installed)
    assert not missing, f"Brewfile formulae not installed: {', '.join(missing)}"


# ── GUI apps ──────────────────────────────────────────────────────────

GUI_APPS = {
    "Ghostty": "/Applications/Ghostty.app",
    "iTerm": "/Applications/iTerm.app",
    "Hammerspoon": "/Applications/Hammerspoon.app",
}


@pytest.mark.parametrize("name,path", GUI_APPS.items(), ids=list(GUI_APPS.keys()))
def test_gui_app_installed(name, path):
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
