"""Terminal, tmux, and SSH configuration checks."""

import os

import pytest

from helpers import TEMPLATE, require_tmux_live_socket, run


# ── Ghostty config ────────────────────────────────────────────────────

@pytest.mark.machine
def test_ghostty_config_valid():
    _, err, rc = run("/Applications/Ghostty.app/Contents/MacOS/ghostty +validate-config")
    assert rc == 0, f"Ghostty config invalid: {err}"


@pytest.mark.machine
def test_ghostty_config_does_not_force_term_downgrade():
    config = os.path.expanduser("~/.config/ghostty/config")
    content = open(config).read()
    assert "term = xterm-256color" not in content


@pytest.mark.machine
def test_ghostty_config_has_local_theme_override():
    config = os.path.expanduser("~/.config/ghostty/config")
    content = open(config).read()
    assert 'config-file = "?~/.config/ghostty/theme.local"' in content


@pytest.mark.machine
def test_ghostty_config_has_expected_font():
    config = os.path.expanduser("~/.config/ghostty/config")
    content = open(config).read()
    assert 'font-family = "Liga SFMono Nerd Font"' in content


@pytest.mark.machine
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
    assert "$(MAKE) syntax-check" in content

# ── SSH config ────────────────────────────────────────────────────────

@pytest.mark.machine
def test_zshrc_defers_host_aliases_to_private_overrides():
    content = open(os.path.expanduser("~/.zshrc")).read()
    assert "Host-specific SSH TERM wrappers belong in ~/.zshrc.local" in content


@pytest.mark.machine
def test_zshrc_skips_ui_plugins_without_tty_even_in_herdr():
    out, err, rc = run("env HERDR_ENV=1 zsh -lic 'printf ZSH_OK'")
    combined = f"{out}\n{err}"

    assert rc == 0
    assert "ZSH_OK" in out
    assert "gitstatus failed to initialize" not in combined
    assert "cannot bind to an empty key sequence" not in combined
    assert "can't change option: zle" not in combined


@pytest.mark.machine
def test_zshrc_defines_fzf_file_and_dir_launchers():
    content = open(os.path.expanduser("~/.zshrc")).read()
    assert "ff()" in content
    assert "fd()" in content
    assert "fzf" in content
    assert "nvim" in content


