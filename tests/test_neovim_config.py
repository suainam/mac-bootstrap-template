"""Neovim configuration checks."""

import os


# ── Neovim config ────────────────────────────────────────────────────

def test_neovim_config_bootstraps_lazyvim():
    config = os.path.expanduser("~/.config/nvim/init.lua")
    content = open(config).read()
    assert 'require("config.lazy")' in content


def test_neovim_config_sets_catppuccin_and_tmux_navigation():
    plugin_file = os.path.expanduser("~/.config/nvim/lua/plugins/core.lua")
    content = open(plugin_file).read()
    assert 'colorscheme = "catppuccin-mocha"' in content
    assert 'vim-tmux-navigator' in content


def test_neovim_config_uses_dedicated_python_host_and_disables_unused_providers():
    init_file = os.path.expanduser("~/.config/nvim/init.lua")
    content = open(init_file).read()
    assert 'python3_host_prog' in content
    assert 'neovim-python/bin/python' in content
    assert 'loaded_perl_provider = 0' in content
    assert 'loaded_ruby_provider = 0' in content
    assert 'loaded_node_provider = 0' in content


def test_neovim_clipboard_uses_local_unnamedplus_and_ssh_fallback():
    options_file = os.path.expanduser("~/.config/nvim/lua/config/options.lua")
    content = open(options_file).read()
    assert 'vim.env.SSH_CONNECTION and "" or "unnamedplus"' in content


def test_neovim_ai_plugin_uses_codecompanion_openai_compatible_adapter():
    plugin_file = os.path.expanduser("~/.config/nvim/lua/plugins/ai.lua")
    content = open(plugin_file).read()
    assert 'olimorris/codecompanion.nvim' in content
    assert 'require("config.private_ai")' in content
    assert 'require("codecompanion.adapters.http.openai_compatible")' in content
    assert 'models_endpoint = "/models"' in content


def test_neovim_ai_completion_plugin_uses_minuet_openai_compatible_virtualtext():
    plugin_file = os.path.expanduser("~/.config/nvim/lua/plugins/ai-completion.lua")
    content = open(plugin_file).read()
    assert 'milanglacier/minuet-ai.nvim' in content
    assert 'provider = "openai_compatible"' in content
    assert 'auto_trigger_ft = { "*" }' in content
    assert 'require("config.private_ai")' in content
    assert 'end_point = base_url .. "/chat/completions"' in content


def test_neovim_yazi_nvim_plugin_integrated():
    plugin_file = os.path.expanduser("~/.config/nvim/lua/plugins/yazi.lua")
    content = open(plugin_file).read()
    assert "mikavilpas/yazi.nvim" in content
    assert 'nvim-lua/plenary.nvim' in content
    assert 'version = "*"' in content
    assert "<leader>y" in content
