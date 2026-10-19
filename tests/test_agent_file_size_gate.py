from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_file_size_gate as gate  # noqa: E402


GATE = ROOT / "scripts" / "agent_file_size_gate.py"


def clean_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHON", None)
    env.pop("PYTHON_BIN", None)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    env.pop("AGENT_RUNTIME_EVENT_JSON", None)
    env.pop("AGENT_RUNTIME_REPO_ROOT", None)
    env.pop("QUALITY_GATES_MAX_FILE_TOKENS", None)
    env.update(overrides)
    return env


def git(repo: Path, env: Mapping[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=dict(env),
        capture_output=True,
        text=True,
        check=True,
    )


def init_repo(repo: Path, env: Mapping[str, str]) -> None:
    repo.mkdir(parents=True)
    git(repo, env, "init", "-q", "-b", "main")
    git(repo, env, "config", "user.email", "file-size@example.com")
    git(repo, env, "config", "user.name", "File Size Gate Test")


def run_gate(repo: Path, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE)],
        cwd=repo,
        env=clean_env(**{"QUALITY_GATES_MAX_FILE_TOKENS": "5000"}),
        capture_output=True,
        text=True,
        check=False,
    )


def stage_text(repo: Path, env: Mapping[str, str], name: str, body: str) -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    git(repo, env, "add", name)


def commit(repo: Path, env: Mapping[str, str], message: str) -> None:
    git(repo, env, "commit", "-qm", message)


def oversized_text(lines: int) -> str:
    """ASCII prose whose byte count lands well above the 5000-token budget."""
    return "\n".join(f"line {index} of a deliberately large text file" for index in range(lines))


def test_new_oversized_text_file_blocks_commit_with_split_guidance(tmp_path: Path):
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)
    stage_text(repo, env, "notes.md", "seed\n")
    commit(repo, env, "initial")

    stage_text(repo, env, "docs/huge.md", oversized_text(2000))
    result = run_gate(repo, env)

    assert result.returncode == 1
    assert "docs/huge.md" in result.stderr
    assert "BLOCK" in result.stderr
    # The error must state the concrete split actions, not just "too big".
    assert "Split before committing" in result.stderr
    assert "sibling files" in result.stderr
    assert "references/" in result.stderr


def test_file_under_budget_passes(tmp_path: Path):
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)
    stage_text(repo, env, "docs/small.md", "short enough\n")
    commit(repo, env, "initial")

    stage_text(repo, env, "docs/medium.md", oversized_text(50))
    result = run_gate(repo, env)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_boundary_is_exact_budget_not_approximately(tmp_path: Path):
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)
    stage_text(repo, env, "seed.md", "seed\n")
    commit(repo, env, "initial")

    # 20000 bytes == exactly 5000 estimated tokens, which is inside the budget.
    stage_text(repo, env, "docs/exact.md", "a" * 20000)
    assert run_gate(repo, env).returncode == 0

    # One more byte crosses it.
    stage_text(repo, env, "docs/over.md", "a" * 20001)
    result = run_gate(repo, env)
    assert result.returncode == 1
    assert "docs/over.md" in result.stderr


def test_preexisting_oversized_file_warns_instead_of_blocking(tmp_path: Path):
    """Ratchet: an already-huge file must stay editable, or the gate deadlocks."""
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)
    stage_text(repo, env, "docs/huge.md", oversized_text(2000))
    # Commit it with the budget lifted, the way history already contains giants.
    commit_oversized = subprocess.run(
        [sys.executable, str(GATE)],
        cwd=repo,
        env=clean_env(QUALITY_GATES_MAX_FILE_TOKENS="1000000"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert commit_oversized.returncode == 0, commit_oversized.stderr
    commit(repo, env, "import legacy giant")

    stage_text(repo, env, "docs/huge.md", oversized_text(2100))
    result = run_gate(repo, env)

    assert result.returncode == 0, result.stderr
    assert "WARN" in result.stdout
    assert "docs/huge.md" in result.stdout
    assert "not blocking" in result.stdout



def test_rename_is_judged_by_destination_not_source(tmp_path: Path):
    """`git mv` out of an ignored dir must not smuggle a giant past the gate.

    Raw diff records list the source path first, so reading the wrong field
    would make `dist/**` suppress measurement of the renamed file.
    """
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)
    stage_text(repo, env, "dist/gen.md", oversized_text(2000))
    commit(repo, env, "import generated giant")

    (repo / "docs").mkdir()
    git(repo, env, "mv", "dist/gen.md", "docs/gen.md")
    result = run_gate(repo, env)

    assert result.returncode == 1
    assert "docs/gen.md" in result.stderr


def test_lockfile_and_generated_paths_are_not_agent_authored(tmp_path: Path):
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)
    stage_text(repo, env, "seed.md", "seed\n")
    commit(repo, env, "initial")

    stage_text(repo, env, "uv.lock", oversized_text(3000))
    stage_text(repo, env, "infra/app/package-lock.json", oversized_text(3000))
    stage_text(repo, env, "infra/app/dist/bundle.js", oversized_text(3000))
    stage_text(repo, env, "infra/app/assets/vendor.min.js", oversized_text(3000))
    stage_text(repo, env, "agent-skills/local/shadows/vendor/SKILL.md", oversized_text(3000))

    result = run_gate(repo, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_chinese_text_gets_a_higher_byte_ceiling_than_english():
    """The budget counts tokens, not bytes: CJK costs ~1 token per character.

    A pure-English file of 20000 bytes estimates 5000 tokens and is inside the
    budget, while a pure-Chinese file of 6000 characters (18000 bytes)
    estimates 6000 tokens and is over it. Without CJK weighting the Chinese
    document would be blocked at half the English budget.
    """
    assert gate.estimate_tokens(b"a" * 20000) == 5000
    assert gate.estimate_tokens(("中文" * 3000).encode("utf-8")) == 6000
    assert gate.estimate_tokens(("中文" * 2500).encode("utf-8")) == 5000
    assert gate.estimate_tokens(b"") == 0


def test_chinese_file_blocks_only_above_the_token_budget(tmp_path: Path):
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)
    stage_text(repo, env, "seed.md", "seed\n")
    commit(repo, env, "initial")

    # 5000 Chinese characters == 5000 estimated tokens == exactly the budget.
    stage_text(repo, env, "docs/zh-at-budget.md", "中文" * 2500)
    assert run_gate(repo, env).returncode == 0

    stage_text(repo, env, "docs/zh-over.md", "中文" * 3001)
    result = run_gate(repo, env)
    assert result.returncode == 1
    assert "docs/zh-over.md" in result.stderr
    assert result.stdout == ""


def test_binary_asset_is_skipped_by_content_sniffing(tmp_path: Path):
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)
    stage_text(repo, env, "seed.md", "seed\n")
    commit(repo, env, "initial")

    binary = repo / "assets" / "hero.unlisted-extension"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 60000)
    git(repo, env, "add", "assets/hero.unlisted-extension")

    result = run_gate(repo, env)

    assert result.returncode == 0, result.stderr


def test_gitlink_staged_entry_is_not_measured_as_a_file(tmp_path: Path):
    """A submodule pointer must not be judged by the parent's byte budget."""
    payload = {
        "event_type": "before.commit",
        "metadata": {
            "staged_entries": [
                {"path": "template", "mode": "160000", "present_in_index": True, "blob_oid": "0" * 40},
            ]
        },
    }
    files = gate.staged_files_from_event(payload)
    assert files == []


def test_deleted_staged_entry_is_skipped(tmp_path: Path):
    payload = {
        "event_type": "before.commit",
        "metadata": {
            "staged_entries": [
                {"path": "gone.md", "mode": "100644", "present_in_index": False, "blob_oid": None},
            ]
        },
    }
    assert gate.staged_files_from_event(payload) == []


def test_event_mode_and_git_index_mode_agree_on_the_same_repository(tmp_path: Path):
    """The hook paths must measure the same index, or one silently under-gates."""
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)
    stage_text(repo, env, "docs/huge.md", oversized_text(2000))
    stage_text(repo, env, "uv.lock", oversized_text(3000))

    from_index = gate.staged_files_from_git(repo)
    assert {entry.path for entry in from_index} == {"docs/huge.md", "uv.lock"}

    payload = {
        "event_type": "before.commit",
        "metadata": {
            "staged_entries": [
                {
                    "path": entry.path,
                    "mode": "100644",
                    "present_in_index": True,
                    "blob_oid": entry.blob_oid,
                }
                for entry in from_index
            ]
        },
    }
    from_event = gate.staged_files_from_event(payload)
    assert [(entry.path, entry.blob_oid) for entry in from_event] == [
        (entry.path, entry.blob_oid) for entry in from_index
    ]

    blocking, warned = gate.collect_oversized(
        from_event,
        repo,
        limit=5000,
        ignore_globs=gate.DEFAULT_IGNORE_GLOBS,
    )
    assert [(entry.path, entry.tokens) for entry in blocking] == [
        ("docs/huge.md", gate.estimate_tokens(oversized_text(2000).encode("utf-8")))
    ]
    assert warned == []


def test_event_mode_blocks_through_the_registry_gate_command(tmp_path: Path):
    """End-to-end: the dispatcher-provided event makes the gate exit non-zero."""
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)
    stage_text(repo, env, "docs/huge.md", oversized_text(2000))
    oid = git(repo, env, "rev-parse", ":docs/huge.md").stdout.strip()

    payload = {
        "schema_version": 1,
        "event_type": "before.commit",
        "metadata": {
            "staged_entries": [
                {
                    "path": "docs/huge.md",
                    "mode": "100644",
                    "present_in_index": True,
                    "blob_oid": oid,
                }
            ]
        },
    }
    result = subprocess.run(
        [sys.executable, str(GATE)],
        cwd=repo,
        env=clean_env(
            AGENT_RUNTIME_REPO_ROOT=str(repo),
            AGENT_RUNTIME_EVENT_JSON=json.dumps(payload),
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "docs/huge.md" in result.stderr


def test_override_env_var_raises_the_budget_for_a_deliberate_exception(tmp_path: Path):
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)
    stage_text(repo, env, "seed.md", "seed\n")
    commit(repo, env, "initial")
    stage_text(repo, env, "docs/huge.md", oversized_text(2000))

    result = subprocess.run(
        [sys.executable, str(GATE)],
        cwd=repo,
        env=clean_env(QUALITY_GATES_MAX_FILE_TOKENS="50000"),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_invalid_override_fails_closed(tmp_path: Path):
    repo = tmp_path / "repo"
    env = clean_env()
    init_repo(repo, env)

    result = subprocess.run(
        [sys.executable, str(GATE)],
        cwd=repo,
        env=clean_env(QUALITY_GATES_MAX_FILE_TOKENS="not-a-number"),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "QUALITY_GATES_MAX_FILE_TOKENS" in result.stderr
