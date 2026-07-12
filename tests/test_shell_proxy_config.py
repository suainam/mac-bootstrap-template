"""Shell environment and proxy configuration checks."""

import os
import subprocess
from pathlib import Path

import pytest

from helpers import TEMPLATE


def test_shell_env_exports_full_proxy_matrix():
    content = open(os.path.join(TEMPLATE, "shell", "shell_env")).read()
    assert "proxy_on()" in content
    assert "proxy_sync_on()" in content
    assert "alias proxy-on='proxy_sync_on'" in content
    assert "alias proxy-off='proxy_sync_off'" in content
    assert "codex_find_writable_root()" in content
    assert 'export CRG_PARSE_EXECUTOR=thread' not in content
    assert 'export CRG_DATA_DIR' not in content
    assert '&& . "$NVM_DIR/nvm.sh"' not in content
    assert '&& . "$HOME/.local/bin/env"' not in content


@pytest.mark.machine
def test_shell_env_redirects_rtk_into_writable_subdir_when_repo_root_is_read_only(tmp_path):
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
                    'printf "RTK_DB_PATH=%s\\n" '
                    '"$RTK_DB_PATH"'
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
    )
    assert result.stdout == expected


@pytest.mark.machine
def test_shell_env_redirects_rtk_into_tmpdir_when_no_workspace_path_is_writable(tmp_path):
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
                    'printf "RTK_DB_PATH=%s\\n" '
                    '"$RTK_DB_PATH"'
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
    assert state_root != repo
    assert str(state_root).startswith(str(tmp_path))


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
