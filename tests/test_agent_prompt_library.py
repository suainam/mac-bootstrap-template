"""Tests for agent prompt-library registry, indexer, and wrappers."""

import json
import os
import subprocess

from helpers import PYTHON, TEMPLATE


def test_prompt_library_sources_registered():
    path = os.path.join(TEMPLATE, "agent", "prompts", "sources.json")
    with open(path, encoding="utf-8") as fh:
        sources = json.load(fh)

    assert sources["prompt_root"] == "~/.agent/prompts"
    assert sources["sources"]["fabric"]["repo"] == "https://github.com/danielmiessler/fabric.git"
    assert sources["sources"]["fabric"]["mode"] == "fabric-patterns"
    assert sources["sources"]["wonderful-prompts"]["repo"] == (
        "https://github.com/langgptai/wonderful-prompts.git"
    )
    assert sources["sources"]["wonderful-prompts"]["mode"] == "markdown-sections"


def test_prompt_library_make_targets_registered():
    content = open(os.path.join(TEMPLATE, "Makefile"), encoding="utf-8").read()
    assert "PYTHON ?= .venv/bin/python" in content
    assert "prompt-sync:" in content
    assert "prompt-index:" in content
    assert "prompt-list:" in content
    assert "prompt-mcp:" in content
    assert "./scripts/sync-agent-prompts.sh" in content
    assert "./scripts/agent-prompt-mcp.sh" in content


def test_prompt_shell_scripts_use_project_python():
    for script in ["agent-prompt.sh", "agent-prompt-mcp.sh", "sync-agent-prompts.sh"]:
        content = open(os.path.join(TEMPLATE, "scripts", script), encoding="utf-8").read()
        assert '$BOOTSTRAP/.venv/bin/python' in content
        assert "python3" not in content


def test_agent_prompt_wrapper_resolves_repo_when_invoked_via_symlink(tmp_path):
    link = tmp_path / "agent-prompt"
    link.symlink_to(os.path.join(TEMPLATE, "scripts", "agent-prompt.sh"))

    result = subprocess.run(
        [str(link), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "agent prompt-library index" in result.stdout


def test_prompt_indexer_builds_and_shows_synthetic_sources(tmp_path):
    upstream = tmp_path / "upstream"
    prompt_root = tmp_path / "prompts"
    index_file = prompt_root / "index.json"

    fabric_pattern = upstream / "fabric" / "data" / "patterns" / "extract_wisdom"
    fabric_pattern.mkdir(parents=True)
    (fabric_pattern / "system.md").write_text(
        "# IDENTITY\nExtract useful insight.\n# INPUT\nINPUT:\n",
        encoding="utf-8",
    )
    (fabric_pattern / "user.md").write_text("Analyze the supplied text.\n", encoding="utf-8")

    wonderful = upstream / "wonderful-prompts"
    wonderful.mkdir(parents=True)
    (wonderful / "README.md").write_text(
        "# Prompts\n\n"
        "## Weekly Report\n\n"
        "# Role: Weekly reporter\n\n"
        "Turn raw work notes into a concise weekly report with risks and next steps.\n",
        encoding="utf-8",
    )

    sources = tmp_path / "sources.json"
    sources.write_text(
        json.dumps(
            {
                "version": 1,
                "prompt_root": str(prompt_root),
                "index_file": str(index_file),
                "sources": {
                    "fabric": {
                        "repo": "https://example.invalid/fabric.git",
                        "upstream_dir": "fabric",
                        "mode": "fabric-patterns",
                        "patterns_path": "data/patterns",
                        "license": "MIT",
                    },
                    "wonderful-prompts": {
                        "repo": "https://example.invalid/wonderful-prompts.git",
                        "upstream_dir": "wonderful-prompts",
                        "mode": "markdown-sections",
                        "files": ["README.md"],
                        "min_section_chars": 20,
                        "license": "MIT",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["AGENT_UPSTREAM_HOME"] = str(upstream)
    script = os.path.join(TEMPLATE, "scripts", "agent-prompt-index.py")

    result = subprocess.run(
        [PYTHON, script, "--sources", str(sources), "build"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    index = json.loads(index_file.read_text(encoding="utf-8"))
    ids = {record["id"] for record in index["prompts"]}
    assert "fabric:extract_wisdom" in ids
    assert "wonderful-prompts:weekly-report" in ids

    shown = subprocess.run(
        [
            PYTHON,
            script,
            "--sources",
            str(sources),
            "--index",
            str(index_file),
            "show",
            "fabric:extract_wisdom",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert shown.returncode == 0, shown.stderr
    assert "Extract useful insight" in shown.stdout
    assert "Analyze the supplied text" in shown.stdout


def test_prompt_indexer_respects_agent_home_for_default_index_path(tmp_path):
    agent_home = tmp_path / "agent-home"
    upstream = agent_home / "upstream"
    fabric_pattern = upstream / "fabric" / "data" / "patterns" / "summarize"
    fabric_pattern.mkdir(parents=True)
    (fabric_pattern / "system.md").write_text("Summarize clearly.\n", encoding="utf-8")

    sources = tmp_path / "sources.json"
    sources.write_text(
        json.dumps(
            {
                "version": 1,
                "prompt_root": "~/.agent/prompts",
                "index_file": "~/.agent/prompts/index.json",
                "sources": {
                    "fabric": {
                        "repo": "https://example.invalid/fabric.git",
                        "upstream_dir": "fabric",
                        "mode": "fabric-patterns",
                        "patterns_path": "data/patterns",
                        "license": "MIT",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["AGENT_HOME"] = str(agent_home)
    result = subprocess.run(
        [PYTHON, os.path.join(TEMPLATE, "scripts", "agent-prompt-index.py"), "--sources", str(sources), "build"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (agent_home / "prompts" / "index.json").exists()
