"""Local CLI, app, font, and Brewfile inventory checks."""

import os

import pytest

from helpers import TEMPLATE, run


# ── CLI tools ─────────────────────────────────────────────────────────

CLI_TOOLS = [
    "git", "curl", "jq", "tree", "rg", "fzf", "tmux", "lua",
    "direnv", "zoxide", "eza", "bat", "yazi", "node", "uv", "pi", "gh",
    "fd", "nvim", "lazygit", "tree-sitter", "ast-grep",
]


@pytest.mark.parametrize("tool", CLI_TOOLS)
def test_cli_tool_available(tool):
    _, _, rc = run(f"command -v {tool}")
    assert rc == 0, f"{tool} not found in PATH"


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
