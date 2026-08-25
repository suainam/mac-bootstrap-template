"""Tests for git worktree parity and .worktreeinclude carryover."""

import os
import subprocess
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "git-worktree-add.sh"
)


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit for worktree operations."""
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"], cwd=path, check=True, capture_output=True
    )


def test_git_worktree_add_carries_worktreeinclude_files(tmp_path: Path) -> None:
    """Verify git-worktree-add.sh automatically carries files listed in .worktreeinclude."""
    _init_git_repo(tmp_path)

    # 1. Setup .worktreeinclude with multiple files and nested paths
    include_content = """# Local secrets and configurations
.env
.env.local
config/secrets.json

# Comments and blank lines should be ignored
"""
    (tmp_path / ".worktreeinclude").write_text(include_content)
    (tmp_path / ".env").write_text("SECRET_KEY=primary_secret\n")
    (tmp_path / ".env.local").write_text("LOCAL_OVERRIDE=true\n")
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "secrets.json").write_text('{"token": "xyz123"}\n')

    # 2. Execute git-worktree-add.sh
    worktree_target = tmp_path / ".worktrees" / "feat-auth"
    res = subprocess.run(
        [str(SCRIPT_PATH), str(worktree_target), "-b", "feat/auth"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Command failed: {res.stderr}"

    # 3. Assert worktree directory and carried files exist with matching content
    assert worktree_target.is_dir()
    assert (worktree_target / ".env").is_file()
    assert (worktree_target / ".env").read_text() == "SECRET_KEY=primary_secret\n"

    assert (worktree_target / ".env.local").is_file()
    assert (worktree_target / ".env.local").read_text() == "LOCAL_OVERRIDE=true\n"

    assert (worktree_target / "config" / "secrets.json").is_file()
    assert (worktree_target / "config" / "secrets.json").read_text() == '{"token": "xyz123"}\n'


def test_git_worktree_add_handles_missing_worktreeinclude_gracefully(
    tmp_path: Path,
) -> None:
    """Verify git-worktree-add.sh behaves like normal git worktree add when .worktreeinclude is absent."""
    _init_git_repo(tmp_path)

    worktree_target = tmp_path / ".worktrees" / "feat-clean"
    res = subprocess.run(
        [str(SCRIPT_PATH), str(worktree_target), "-b", "feat/clean"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Command failed: {res.stderr}"
    assert worktree_target.is_dir()
    assert (worktree_target / "README.md").is_file()


def test_git_worktree_add_skips_missing_include_targets_without_error(
    tmp_path: Path,
) -> None:
    """Verify nonexistent targets in .worktreeinclude are safely ignored."""
    _init_git_repo(tmp_path)

    include_content = """.env
missing_secret.json
"""
    (tmp_path / ".worktreeinclude").write_text(include_content)
    (tmp_path / ".env").write_text("FOO=bar\n")

    worktree_target = tmp_path / ".worktrees" / "feat-partial"
    res = subprocess.run(
        [str(SCRIPT_PATH), str(worktree_target), "-b", "feat/partial"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Command failed: {res.stderr}"
    assert (worktree_target / ".env").read_text() == "FOO=bar\n"
    assert not (worktree_target / "missing_secret.json").exists()
