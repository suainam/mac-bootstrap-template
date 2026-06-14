"""Regression tests for mac-bootstrap symlinks, configs, and tooling."""

import os
import subprocess

import pytest


HOME = os.path.expanduser("~")
TEMPLATE = os.path.join(HOME, "work", "config", "mac-bootstrap", "template")


def run(cmd: str) -> tuple[str, str, int]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


# ── Symlink health ────────────────────────────────────────────────────

SYMLINKS = [
    "~/.zprofile",
    "~/.zshenv",
    "~/.zshrc",
    "~/.shell_env",
    "~/.bash_profile",
    "~/.p10k.zsh",
    "~/.hammerspoon/init.lua",
    "~/.tmux.conf",
    "~/.tmux/theme.conf",
    "~/.config/ghostty/config",
    "~/.local/bin/tmux-workspace.sh",
]


@pytest.mark.parametrize("path", SYMLINKS)
def test_symlink_not_broken(path):
    expanded = os.path.expanduser(path)
    assert os.path.islink(expanded), f"{path} is not a symlink"
    assert os.path.exists(expanded), f"{path} is a broken symlink"


# ── CLI tools ─────────────────────────────────────────────────────────

CLI_TOOLS = [
    "git", "curl", "jq", "tree", "rg", "fzf", "tmux", "lua",
    "direnv", "zoxide", "eza", "bat", "node", "uv", "pi", "gh",
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


# ── Ghostty config ────────────────────────────────────────────────────

def test_ghostty_config_valid():
    _, err, rc = run("/Applications/Ghostty.app/Contents/MacOS/ghostty +validate-config")
    assert rc == 0, f"Ghostty config invalid: {err}"


def test_ghostty_config_has_term_compat():
    config = os.path.expanduser("~/.config/ghostty/config")
    content = open(config).read()
    assert "term = xterm-256color" in content


# ── tmux config ───────────────────────────────────────────────────────

def test_tmux_config_loadable():
    _, err, rc = run("tmux show-option -g prefix")
    assert rc == 0, f"tmux config error: {err}"


def test_tmux_has_swap_pane_keys():
    out, _, _ = run("tmux list-keys 2>/dev/null | grep -c swap-pane")
    assert int(out) >= 4, "Expected at least 4 swap-pane keybindings"


def test_tmux_has_cross_window_swap():
    out, _, _ = run("tmux list-keys 2>/dev/null | grep 'command-prompt.*swap-pane'")
    assert out, "Cross-window swap-pane keybinding (C-a X) not found"


def test_tmux_pane_titles():
    out, _, _ = run("tmux list-panes -F '#{pane_title}' 2>/dev/null")
    titles = out.strip().split('\n')
    assert 'claude-keepalive' in titles, f"Missing pane title 'claude-keepalive', got: {titles}"
    assert 'dsliam' in titles, f"Missing pane title 'dsliam', got: {titles}"
    assert 'work' in titles, f"Missing pane title 'work', got: {titles}"


def test_tmux_pane_border_format_shows_title():
    out, _, _ = run("tmux show-option -g pane-border-format")
    assert 'pane_title' in out, f"pane-border-format doesn't reference pane_title: {out}"


def test_tmux_theme_exists():
    path = os.path.expanduser("~/.tmux/theme.conf")
    assert os.path.exists(path)


# ── Hammerspoon ───────────────────────────────────────────────────────

def test_hammerspoon_has_ghostty_binding():
    content = open(os.path.expanduser("~/.hammerspoon/init.lua")).read()
    assert "ghostty_bundle_id" in content


def test_hammerspoon_has_iterm2_binding():
    content = open(os.path.expanduser("~/.hammerspoon/init.lua")).read()
    assert "iterm2_bundle_id" in content


def test_hammerspoon_ghostty_in_input_switcher():
    content = open(os.path.expanduser("~/.hammerspoon/init.lua")).read()
    assert '"Ghostty"' in content


# ── SSH config ────────────────────────────────────────────────────────

def test_ssh_dsliam_mux_exists():
    content = open(os.path.expanduser("~/.ssh/config.d/dsliam")).read()
    assert "Host dsliam-mux" in content


def test_ssh_dsliam_devpod_removed():
    content = open(os.path.expanduser("~/.ssh/config.d/dsliam")).read()
    assert "dsliam-devpod" not in content


def test_ssh_controlmaster_auto():
    content = open(os.path.expanduser("~/.ssh/config.d/dsliam")).read()
    assert "ControlMaster auto" in content


# ── Font ──────────────────────────────────────────────────────────────

def test_font_installed():
    font = os.path.expanduser("~/Library/Fonts/LigaSFMonoNerdFont-Regular.otf")
    assert os.path.exists(font), "LigaSFMono Nerd Font not found"


# ── Hammerspoon Spoons ────────────────────────────────────────────────

def test_spoons_installed():
    spoons = os.listdir(os.path.expanduser("~/.hammerspoon/Spoons"))
    assert "ClipboardTool.spoon" in spoons
    assert "HSKeybindings.spoon" in spoons


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


# ── code-server infra ─────────────────────────────────────────────────

def test_code_server_dockerfile_exists():
    path = os.path.join(TEMPLATE, "infra", "code-server", "Dockerfile")
    assert os.path.exists(path)


def test_code_server_docker_compose_exists():
    path = os.path.join(TEMPLATE, "infra", "code-server", "docker-compose.yml")
    assert os.path.exists(path)


def test_code_server_dockerfile_has_docker_cli():
    content = open(os.path.join(TEMPLATE, "infra", "code-server", "Dockerfile")).read()
    assert "docker-ce-cli" in content
    assert "docker-compose-plugin" in content


def test_code_server_compose_mounts_docker_sock():
    content = open(os.path.join(TEMPLATE, "infra", "code-server", "docker-compose.yml")).read()
    assert "/var/run/docker.sock" in content
