from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts" / "agent_claude_edit_adapter.py"
REGISTRY = ROOT / "agent" / "runtime" / "registry.jsonc"


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def init_repo(repo: Path) -> None:
    repo.mkdir()
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.email", "tracer@example.com")
    run_git(repo, "config", "user.name", "Tracer Test")
    run_git(repo, "config", "--local", "agent.runtime.enabled", "true")
    run_git(repo, "config", "--local", "agent.runtime.profile", "claude-edit-smoke")


def claude_payload(repo: Path, file_path: Path, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "session_id": "session-tracer-001",
        "transcript_path": str(repo / "must-not-be-read.jsonl"),
        "cwd": str(repo),
        "permission_mode": "default",
        "hook_event_name": "PostToolUse",
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(file_path),
            "content": "not-used-by-adapter",
        },
        "tool_response": {
            "filePath": str(file_path),
            "success": True,
        },
        "tool_use_id": "toolu_tracer_001",
    }
    payload.update(overrides)
    return payload


def run_adapter(
    repo: Path,
    home: Path,
    payload: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("PYTHON", None)
    env.pop("PYTHON_BIN", None)
    return subprocess.run(
        [
            sys.executable,
            str(ADAPTER),
            "--registry",
            str(REGISTRY),
            "hook",
        ],
        cwd=repo,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_real_after_edit_syntax_failure_reaches_claude_then_deduplicates(tmp_path: Path):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    init_repo(repo)
    target = repo / "sample.py"
    target.write_text("def broken(:\n    pass\n", encoding="utf-8")
    payload = claude_payload(repo, target)

    first = run_adapter(repo, home, payload)
    repeated = run_adapter(repo, home, payload)

    assert first.returncode == 0
    assert first.stderr == ""
    feedback = json.loads(first.stdout)
    assert feedback["decision"] == "block"
    assert "python-syntax-smoke" in feedback["reason"]
    assert "SyntaxError" in feedback["reason"] or "invalid syntax" in feedback["reason"]
    assert repeated.returncode == 0
    assert repeated.stdout == ""
    assert repeated.stderr == ""
    assert (repo / "must-not-be-read.jsonl").exists() is False


def test_fixed_file_is_silent(tmp_path: Path):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    init_repo(repo)
    target = repo / "sample.py"
    target.write_text("def working():\n    return 1\n", encoding="utf-8")

    result = run_adapter(repo, home, claude_payload(repo, target))

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_only_post_tool_use_edit_or_write_is_accepted(tmp_path: Path):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    init_repo(repo)
    target = repo / "sample.py"
    target.write_text("value = 1\n", encoding="utf-8")

    wrong_event = run_adapter(
        repo,
        home,
        claude_payload(repo, target, hook_event_name="Stop"),
    )
    wrong_tool = run_adapter(
        repo,
        home,
        claude_payload(repo, target, tool_name="Bash"),
    )

    assert wrong_event.returncode == 2
    assert wrong_event.stdout == ""
    assert "expected PostToolUse" in wrong_event.stderr
    assert wrong_tool.returncode == 2
    assert wrong_tool.stdout == ""
    assert "expected Edit or Write" in wrong_tool.stderr


def test_target_must_belong_to_the_repository(tmp_path: Path):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    init_repo(repo)
    outside = tmp_path / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")

    result = run_adapter(repo, home, claude_payload(repo, outside))

    assert result.returncode == 2
    assert result.stdout == ""
    assert "outside repository" in result.stderr


def test_settings_command_emits_one_minimal_edit_hook(tmp_path: Path):
    python = Path(sys.executable).resolve()
    result = subprocess.run(
        [
            sys.executable,
            str(ADAPTER),
            "--registry",
            str(REGISTRY),
            "settings",
            "--python",
            str(python),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    settings = json.loads(result.stdout)
    groups = settings["hooks"]["PostToolUse"]
    assert len(groups) == 1
    assert groups[0]["matcher"] == "Edit|Write"
    handlers = groups[0]["hooks"]
    assert len(handlers) == 1
    assert handlers[0]["type"] == "command"
    assert handlers[0]["command"] == " ".join(
        [
            str(python),
            str(ADAPTER.resolve()),
            "--registry",
            str(REGISTRY.resolve()),
            "hook",
        ]
    )
    assert handlers[0]["timeout"] == 30
    assert "SessionStart" not in settings["hooks"]
    assert "PostToolBatch" not in settings["hooks"]
