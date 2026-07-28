from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts" / "agent_opencode_edit_adapter.py"
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


def opencode_payload(
    repo: Path,
    file_path: Path,
    *,
    tool: str = "write",
    args: dict[str, object] | None = None,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "input": {
            "tool": tool,
            "sessionID": "ses_tracer_001",
            "callID": "call_tracer_001",
            "args": args
            or {
                "filePath": str(file_path),
                "content": "not-used-by-adapter",
            },
        },
        "output": {
            "title": str(file_path),
            "output": "Wrote file successfully.",
            "metadata": {
                "filepath": str(file_path),
                "exists": True,
            },
        },
        "directory": str(repo),
        "worktree": str(repo),
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


def test_real_after_edit_syntax_failure_reaches_opencode_then_deduplicates(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    init_repo(repo)
    target = repo / "sample.py"
    target.write_text("def broken(:\n    pass\n", encoding="utf-8")
    payload = opencode_payload(repo, target)

    first = run_adapter(repo, home, payload)
    repeated = run_adapter(repo, home, payload)

    assert first.returncode == 0
    assert first.stderr == ""
    feedback = json.loads(first.stdout)
    assert set(feedback) == {"additionalContext"}
    reason = feedback["additionalContext"]
    assert "python-syntax-smoke" in reason
    assert "SyntaxError" in reason or "invalid syntax" in reason
    assert repeated.returncode == 0
    assert repeated.stdout == ""
    assert repeated.stderr == ""


@pytest.mark.parametrize("tool", ["write", "edit"])
def test_fixed_write_or_edit_is_silent(tmp_path: Path, tool: str):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    init_repo(repo)
    target = repo / "sample.py"
    target.write_text("def working():\n    return 1\n", encoding="utf-8")

    result = run_adapter(repo, home, opencode_payload(repo, target, tool=tool))

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_single_file_apply_patch_uses_marker_path(tmp_path: Path):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    init_repo(repo)
    target = repo / "sample.py"
    target.write_text("def broken(:\n    pass\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: sample.py
@@
-def working():
+def broken(:
*** End Patch
"""

    result = run_adapter(
        repo,
        home,
        opencode_payload(
            repo,
            target,
            tool="apply_patch",
            args={"patchText": patch},
        ),
    )

    assert result.returncode == 0
    feedback = json.loads(result.stdout)
    assert "python-syntax-smoke" in feedback["additionalContext"]


def test_multi_file_apply_patch_is_rejected(tmp_path: Path):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    init_repo(repo)
    first = repo / "first.py"
    second = repo / "second.py"
    first.write_text("value = 1\n", encoding="utf-8")
    second.write_text("value = 2\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: first.py
@@
-value = 0
+value = 1
*** Update File: second.py
@@
-value = 0
+value = 2
*** End Patch
"""

    result = run_adapter(
        repo,
        home,
        opencode_payload(
            repo,
            first,
            tool="apply_patch",
            args={"patchText": patch},
        ),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "exactly one target file" in result.stderr


def test_only_supported_edit_tools_are_accepted(tmp_path: Path):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    init_repo(repo)
    target = repo / "sample.py"
    target.write_text("value = 1\n", encoding="utf-8")

    result = run_adapter(repo, home, opencode_payload(repo, target, tool="bash"))

    assert result.returncode == 2
    assert result.stdout == ""
    assert "expected write, edit, or apply_patch" in result.stderr


def test_target_must_belong_to_the_repository(tmp_path: Path):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    init_repo(repo)
    outside = tmp_path / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")

    result = run_adapter(repo, home, opencode_payload(repo, outside))

    assert result.returncode == 2
    assert result.stdout == ""
    assert "outside repository" in result.stderr


def test_plugin_command_emits_one_minimal_after_tool_shim(tmp_path: Path):
    python = Path(sys.executable).resolve()
    result = subprocess.run(
        [
            sys.executable,
            str(ADAPTER),
            "--registry",
            str(REGISTRY),
            "plugin",
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
    source = result.stdout
    assert '"tool.execute.after"' in source
    assert '"write"' in source
    assert '"edit"' in source
    assert '"apply_patch"' in source
    assert str(python) in source
    assert str(ADAPTER.resolve()) in source
    assert str(REGISTRY.resolve()) in source
    assert "session.created" not in source
    assert "session.idle" not in source
    assert "file.edited" not in source

    plugin = tmp_path / "plugin.mjs"
    plugin.write_text(source, encoding="utf-8")
    syntax = subprocess.run(
        ["node", "--check", str(plugin)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr
