"""Terminal, tmux, and SSH configuration checks."""

import os

from helpers import TEMPLATE, require_tmux_live_socket, run


# ── Ghostty config ────────────────────────────────────────────────────

def test_ghostty_config_valid():
    _, err, rc = run("/Applications/Ghostty.app/Contents/MacOS/ghostty +validate-config")
    assert rc == 0, f"Ghostty config invalid: {err}"


def test_ghostty_config_does_not_force_term_downgrade():
    config = os.path.expanduser("~/.config/ghostty/config")
    content = open(config).read()
    assert "term = xterm-256color" not in content


def test_ghostty_config_has_local_theme_override():
    config = os.path.expanduser("~/.config/ghostty/config")
    content = open(config).read()
    assert 'config-file = "?~/.config/ghostty/theme.local"' in content


def test_ghostty_config_has_expected_font():
    config = os.path.expanduser("~/.config/ghostty/config")
    content = open(config).read()
    assert 'font-family = "Liga SFMono Nerd Font"' in content


def test_ghostty_config_pins_cjk_fallback():
    config = os.path.expanduser("~/.config/ghostty/config")
    content = open(config).read()
    assert "font-codepoint-map = U+4E00-U+9FFF=PingFang SC" in content
    assert "font-codepoint-map = U+FF00-U+FFEF=PingFang SC" in content


def test_ghostty_font_repair_script_registers_existing_liga_fonts():
    script = os.path.join(TEMPLATE, "terminals", "ghostty", "repair-fonts.sh")
    content = open(script).read()
    assert "LigaSFMonoNerdFont-*.otf" in content
    assert "com.apple.FontRegistry.user.plist" in content
    assert "com.apple.quarantine" in content
    assert "CTFontManagerRegisterFontsForURL" in content
    assert "Liga SFMono Nerd Font" in content


def test_makefile_checks_ghostty_font_repair_script():
    content = open(os.path.join(TEMPLATE, "Makefile")).read()
    assert "ghostty-font-repair:" in content
    assert "bash -n terminals/ghostty/repair-fonts.sh" in content

# ── tmux config ───────────────────────────────────────────────────────

def test_tmux_config_loadable():
    require_tmux_live_socket()


def test_tmux_has_swap_pane_keys():
    require_tmux_live_socket()
    out, _, _ = run("tmux list-keys 2>/dev/null | grep -c swap-pane")
    assert int(out) >= 4, "Expected at least 4 swap-pane keybindings"


def test_tmux_has_cross_window_swap():
    require_tmux_live_socket()
    out, _, _ = run("tmux list-keys 2>/dev/null | grep 'command-prompt.*swap-pane'")
    assert out, "Cross-window swap-pane keybinding (C-a X) not found"


def test_tmux_pane_titles():
    workspace_script = open(os.path.join(TEMPLATE, "scripts", "tmux-workspace.sh")).read()
    assert 'ANALYSIS_WINDOW="${TMUX_ANALYSIS_WINDOW:-analysis}"' in workspace_script
    assert 'create_analysis_window()' in workspace_script
    assert '"shell"' in workspace_script
    assert '"python"' in workspace_script
    assert '"sql"' in workspace_script
    assert '"notes"' in workspace_script
    assert '"daemon"' in workspace_script

    require_tmux_live_socket()
    out, _, _ = run("tmux list-panes -F '#{pane_title}' 2>/dev/null")
    titles = [title for title in out.strip().split('\n') if title]
    assert titles, "Expected tmux panes to expose non-empty titles"


def test_tmux_pane_border_format_shows_title():
    require_tmux_live_socket()
    out, _, _ = run("tmux show-option -g pane-border-format")
    assert 'pane_title' in out, f"pane-border-format doesn't reference pane_title: {out}"
    assert 'pane-#{pane_index}' in out, f"pane-border-format doesn't use generic fallback: {out}"


def test_tmux_theme_exists():
    path = os.path.expanduser("~/.tmux/theme.conf")
    assert os.path.exists(path)


def test_tmux_config_resets_append_only_options_before_readding():
    config = os.path.expanduser("~/.tmux.conf")
    content = open(config).read()
    assert "set -gu terminal-features" in content
    assert "set -gu update-environment" in content

# ── SSH config ────────────────────────────────────────────────────────

def test_zshrc_defers_host_aliases_to_private_overrides():
    content = open(os.path.expanduser("~/.zshrc")).read()
    assert "Host-specific SSH TERM wrappers belong in ~/.zshrc.local" in content


def test_zshrc_defines_fzf_file_and_dir_launchers():
    content = open(os.path.expanduser("~/.zshrc")).read()
    assert "ff()" in content
    assert "fd()" in content
    assert "fzf" in content
    assert "nvim" in content
