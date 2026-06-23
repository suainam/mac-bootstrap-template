"""Regression tests for mac-bootstrap symlinks, configs, and tooling."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


HOME = os.path.expanduser("~")
TEMPLATE = os.path.join(HOME, "work", "config", "mac-bootstrap", "template")
DOCTOR_MANIFEST = os.path.join(TEMPLATE, "scripts", "doctor-manifest.json")


def run(cmd: str) -> tuple[str, str, int]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


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


# ── Symlink health ────────────────────────────────────────────────────


def managed_symlinks() -> dict[str, str]:
    manifest = json.loads(open(DOCTOR_MANIFEST).read())
    return manifest["managed_symlinks"]


@pytest.mark.parametrize("path", managed_symlinks().keys())
def test_symlink_not_broken(path):
    expanded = os.path.expanduser(path)
    assert os.path.islink(expanded), f"{path} is not a symlink"
    assert os.path.exists(expanded), f"{path} is a broken symlink"


@pytest.mark.parametrize("path,target", managed_symlinks().items())
def test_symlink_points_to_current_target(path, target):
    assert os.path.realpath(os.path.expanduser(path)) == os.path.join(TEMPLATE, target)


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


def test_sync_codex_mcp_config_deduplicates_managed_tables():
    script = os.path.join(TEMPLATE, "scripts", "sync-codex-mcp-config.py")
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Path(tmpdir) / "config.toml"
        block = Path(tmpdir) / "block.toml"
        config.write_text(
            'model = "gpt-5"\n'
            '\n'
            '[mcp_servers.context-mode.tools.ctx_search]\n'
            'approval_mode = "approve"\n'
            '\n'
            '[mcp_servers.context7.env]\n'
            'HTTP_PROXY = "http://old"\n'
            '\n'
            '[mcp_servers.code-review-graph]\n'
            'command = "old"\n'
        )
        block.write_text(
            '# BEGIN MAC-BOOTSTRAP MANAGED MCPS\n'
            '[mcp_servers.context-mode]\n'
            'command = "context-mode"\n'
            'args = []\n'
            '\n'
            '[mcp_servers.context-mode.tools.ctx_search]\n'
            'approval_mode = "approve"\n'
            '# END MAC-BOOTSTRAP MANAGED MCPS\n'
        )

        _, err, rc = run(f'python3 "{script}" "{config}" "{block}"')
        assert rc == 0, err
        content = config.read_text()

        assert content.count("[mcp_servers.context-mode.tools.ctx_search]") == 1
        assert content.count("[mcp_servers.context7.env]") == 0
        assert content.count("# BEGIN MAC-BOOTSTRAP MANAGED MCPS") == 1
        assert 'model = "gpt-5"' in content


def test_shell_env_exports_full_proxy_matrix():
    content = open(os.path.join(TEMPLATE, "shell", "shell_env")).read()
    assert "proxy_on()" in content
    assert "proxy_sync_on()" in content
    assert "alias proxy-on='proxy_sync_on'" in content
    assert "alias proxy-off='proxy_sync_off'" in content
    assert "codex_find_writable_root()" in content
    assert 'export CRG_PARSE_EXECUTOR=thread' in content
    assert 'export CRG_DATA_DIR="$_state_root/.code-review-graph"' in content
    assert '&& . "$NVM_DIR/nvm.sh"' not in content
    assert '&& . "$HOME/.local/bin/env"' not in content


def test_shell_env_redirects_crg_into_writable_subdir_when_repo_root_is_read_only(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    writable = repo / "writable"
    writable.mkdir()
    shell_env = os.path.join(TEMPLATE, "shell", "shell_env")
    repo.chmod(0o555)
    try:
        result = subprocess.run(
            [
                "zsh",
                "-lc",
                (
                    f'cd "{writable}" && export CODEX_SANDBOX=seatbelt && '
                    f'source "{shell_env}" && '
                    'printf "RTK_DB_PATH=%s\\nCRG_DATA_DIR=%s\\nCRG_PARSE_EXECUTOR=%s\\n" '
                    '"$RTK_DB_PATH" "$CRG_DATA_DIR" "$CRG_PARSE_EXECUTOR"'
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    finally:
        repo.chmod(0o755)
    expected = (
        f"RTK_DB_PATH={writable}/.rtk-state/history.db\n"
        f"CRG_DATA_DIR={writable}/.code-review-graph\n"
        "CRG_PARSE_EXECUTOR=thread\n"
    )
    assert result.stdout == expected


def test_shell_env_redirects_crg_into_tmpdir_when_no_workspace_path_is_writable(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    locked = repo / "locked"
    locked.mkdir()
    shell_env = os.path.join(TEMPLATE, "shell", "shell_env")
    repo.chmod(0o555)
    locked.chmod(0o555)
    try:
        result = subprocess.run(
            [
                "zsh",
                "-lc",
                (
                    f'cd "{locked}" && export CODEX_SANDBOX=seatbelt && '
                    f'source "{shell_env}" && '
                    'printf "RTK_DB_PATH=%s\\nCRG_DATA_DIR=%s\\nCRG_PARSE_EXECUTOR=%s\\n" '
                    '"$RTK_DB_PATH" "$CRG_DATA_DIR" "$CRG_PARSE_EXECUTOR"'
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    finally:
        locked.chmod(0o755)
        repo.chmod(0o755)
    lines = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    state_root = Path(lines["RTK_DB_PATH"]).parent.parent
    assert lines["RTK_DB_PATH"] == str(state_root / ".rtk-state" / "history.db")
    assert lines["CRG_DATA_DIR"] == str(state_root / ".code-review-graph")
    assert state_root != repo
    assert str(state_root).startswith(str(tmp_path))
    assert lines["CRG_PARSE_EXECUTOR"] == "thread"


def test_configure_proxies_sets_git_proxy():
    content = open(os.path.join(TEMPLATE, "scripts", "configure-proxies.sh")).read()
    assert '. "$LIB"' in content
    assert "load_proxy_env_from_shell_env" in content
    assert 'write_git_proxy_include "$GIT_PROXY_TEMPLATE" "$GIT_PROXY_TARGET"' in content


def test_clear_proxies_clears_git_proxy():
    content = open(os.path.join(TEMPLATE, "scripts", "clear-proxies.sh")).read()
    assert '. "$LIB"' in content
    assert 'clear_git_proxy_include "$GIT_PROXY_TARGET"' in content


def test_git_proxy_template_exists():
    content = open(os.path.join(TEMPLATE, "shell", "gitconfig.proxy.template")).read()
    assert "__HTTP_PROXY__" in content
    assert "__HTTPS_PROXY__" in content


def test_proxy_common_library_has_shared_functions():
    content = open(os.path.join(TEMPLATE, "scripts", "lib", "proxy-common.sh")).read()
    assert "load_proxy_env_from_shell_env()" in content
    assert "write_git_proxy_include()" in content
    assert "clear_git_proxy_include()" in content


def test_render_codex_mcp_block_emits_proxy_variants():
    script = os.path.join(TEMPLATE, "scripts", "render-codex-mcp-block.py")
    env = {
        **os.environ,
        "HTTP_PROXY": "http://127.0.0.1:7897",
        "HTTPS_PROXY": "http://127.0.0.1:7897",
        "ALL_PROXY": "http://127.0.0.1:7897",
        "NO_PROXY": "localhost,127.0.0.1,::1",
    }
    r = subprocess.run(
        ["python3", script, "--context7-command", "npx"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, r.stderr
    assert 'command = "npx"' in r.stdout
    assert 'args = ["-y", "@upstash/context7-mcp"]' in r.stdout
    assert 'all_proxy = "http://127.0.0.1:7897"' in r.stdout
    assert 'NO_PROXY = "localhost,127.0.0.1,::1"' in r.stdout


def test_check_python_syntax_parses_files():
    script = os.path.join(TEMPLATE, "scripts", "check-python-syntax.py")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "ok.py"
        path.write_text("x = 1\n")
        out, err, rc = run(f'python3 "{script}" "{path}"')
        assert rc == 0, err
        assert f"ok {path}" in out


def test_doctor_uses_capability_checks():
    content = open(os.path.join(TEMPLATE, "scripts", "doctor.sh")).read()
    assert 'run-doctor-checks.py' in content
    assert 'doctor-manifest.json' in content


def test_doctor_manifest_captures_overrides():
    content = open(os.path.join(TEMPLATE, "scripts", "doctor-manifest.json")).read()
    assert '"ripgrep": "rg"' in content
    assert '"claude-code"' in content
    assert '"cc-switch"' in content


def test_run_doctor_checks_parses_manifest():
    content = open(os.path.join(TEMPLATE, "scripts", "run-doctor-checks.py")).read()
    assert 'formula_command_overrides' in content
    assert 'cask_overrides' in content
    assert 'standalone_clis' in content


def test_install_agent_tooling_is_thin_orchestrator():
    content = open(os.path.join(TEMPLATE, "scripts", "install-agent-tooling.sh")).read()
    assert '. "$BOOTSTRAP/scripts/lib/agent-mcp.sh"' in content
    assert '. "$BOOTSTRAP/scripts/lib/agent-configure.sh"' in content
    assert "configure_all_mcp" in content
    assert len(content.splitlines()) < 250


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


def test_zshrc_has_dsliam_term_wrappers():
    content = open(os.path.expanduser("~/.zshrc")).read()
    assert "alias dsliam='TERM=xterm-256color command ssh dsliam'" in content
    assert "alias dsliam-mux='TERM=xterm-256color command ssh dsliam-mux'" in content


def test_runtime_dsliam_alias_downgrades_term():
    out, _, rc = run("script -q /dev/null zsh -ic 'alias dsliam'")
    assert rc == 0
    assert "TERM=xterm-256color command ssh dsliam" in out


def test_runtime_dsliam_mux_alias_downgrades_term():
    out, _, rc = run("script -q /dev/null zsh -ic 'alias dsliam-mux'")
    assert rc == 0
    assert "TERM=xterm-256color command ssh dsliam-mux" in out


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


def test_brewfile_has_codex_threadripper():
    content = open(os.path.join(TEMPLATE, "Brewfile")).read()
    assert 'tap "wangnov/tap"' in content
    assert 'brew "codex-threadripper"' in content


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


def test_code_server_paths_are_parameterized():
    install = open(os.path.join(TEMPLATE, "infra", "code-server", "install.sh")).read()
    compose = open(os.path.join(TEMPLATE, "infra", "code-server", "docker-compose.yml")).read()
    assert 'CODE_SERVER_DIR:-/srv/code-server' in install
    assert '${CODE_SERVER_WORKSPACE_DIR:-/workspace}:/root/dev' in compose
