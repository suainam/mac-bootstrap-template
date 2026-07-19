from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "agent-skills/local/global/curate-repo-knowledge/scripts/audit_project.py"


def run_audit(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDIT), str(project), "--format", "json", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_audit_reports_lean_single_source_project_without_mutation(
    tmp_path: Path,
) -> None:
    claude = tmp_path / "CLAUDE.md"
    claude.write_text(
        "# Rules\n\n- Run `pytest`.\n- Read [context](CONTEXT.md).\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")
    (tmp_path / "CONTEXT.md").write_text("# Context\n", encoding="utf-8")
    before = sorted(path.name for path in tmp_path.iterdir())

    result = run_audit(tmp_path)

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["schema_version"] == "curate-repo-knowledge.audit/v1"
    assert report["summary"] == {
        "error_count": 0,
        "warning_count": 0,
        "candidate_count": 0,
    }
    assert report["agent_source"]["status"] == "single-source"
    assert report["agent_source"]["canonical_path"] == "CLAUDE.md"
    assert report["agent_source"]["aliases"] == ["AGENTS.md"]
    assert report["measurements"]["CLAUDE.md"]["non_empty_lines"] == 3
    assert report["measurements"]["CLAUDE.md"]["total_lines"] == 4
    assert sorted(path.name for path in tmp_path.iterdir()) == before


def test_audit_fails_strict_mode_for_budget_and_dead_link(tmp_path: Path) -> None:
    lines = ["# Rules", "", "- [missing](docs/missing.md)"]
    lines.extend(f"- project-specific rule {index}" for index in range(79))
    (tmp_path / "AGENTS.md").write_text("\n".join(lines), encoding="utf-8")

    result = run_audit(tmp_path, "--strict")

    assert result.returncode == 1
    report = json.loads(result.stdout)
    codes = {finding["code"] for finding in report["findings"]}
    assert "PERSISTENT_LINE_BUDGET_EXCEEDED" in codes
    assert "DEAD_LOCAL_LINK" in codes
    assert report["summary"]["error_count"] == 2


def test_audit_enforces_total_line_budget_including_blank_lines(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Rules\n" + "\n" * 80, encoding="utf-8")

    result = run_audit(tmp_path, "--strict")
    report = json.loads(result.stdout)

    assert result.returncode == 1
    assert report["measurements"]["AGENTS.md"]["total_lines"] == 81
    assert any(
        item["code"] == "PERSISTENT_LINE_BUDGET_EXCEEDED"
        and item["evidence"]["metric"] == "total_lines"
        for item in report["findings"]
    )


def test_audit_marks_independent_agent_files_as_authority_conflict(
    tmp_path: Path,
) -> None:
    (tmp_path / "AGENTS.md").write_text("# Codex rules\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Claude rules\n", encoding="utf-8")

    result = run_audit(tmp_path, "--strict")

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["agent_source"]["status"] == "conflict"
    assert any(
        finding["code"] == "AGENT_AUTHORITY_CONFLICT"
        and finding["mutation_class"] == "review-required"
        for finding in report["findings"]
    )


def test_audit_keeps_semantic_duplication_as_candidate(tmp_path: Path) -> None:
    shared = "Deployments must use the project Make targets."
    (tmp_path / "AGENTS.md").write_text(f"# Rules\n\n{shared}\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(f"# Project\n\n{shared}\n", encoding="utf-8")

    result = run_audit(tmp_path)

    assert result.returncode == 0
    report = json.loads(result.stdout)
    candidates = [
        finding
        for finding in report["findings"]
        if finding["code"] == "POSSIBLE_DUPLICATE_FACT"
    ]
    assert len(candidates) == 1
    assert candidates[0]["severity"] == "candidate"
    assert candidates[0]["mutation_class"] == "review-required"


def test_audit_excludes_archives_and_worktrees(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
    for relative in (
        "docs/archive/old.md",
        "docs/Retrospectives/old.md",
        ".worktrees/other/AGENTS.md",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[dead](missing.md)\n", encoding="utf-8")

    result = run_audit(tmp_path, "--strict")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert set(report["measurements"]) == {"AGENTS.md"}


def test_audit_includes_active_dot_directory_authorities(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
    authority = tmp_path / ".github/instructions.md"
    authority.parent.mkdir()
    authority.write_text("# GitHub authority\n", encoding="utf-8")

    report = json.loads(run_audit(tmp_path).stdout)

    assert ".github/instructions.md" in report["measurements"]


def test_audit_ignores_markdown_shaped_text_inside_fenced_code(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Example\n\n```python\nvalue = call[arg](not/a/link.md)\n```\n",
        encoding="utf-8",
    )

    result = run_audit(tmp_path, "--strict")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert all(item["code"] != "DEAD_LOCAL_LINK" for item in report["findings"])


def test_audit_respects_git_ignored_knowledge_surfaces(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("third_party/\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
    ignored = tmp_path / "third_party/README.md"
    ignored.parent.mkdir()
    ignored.write_text("[dead](missing.md)\n", encoding="utf-8")

    result = run_audit(tmp_path, "--strict")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert set(report["measurements"]) == {"AGENTS.md"}


def test_audit_respects_parent_gitignore_for_nested_project(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("project/third_party/\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
    ignored = project / "third_party/README.md"
    ignored.parent.mkdir()
    ignored.write_text("[dead](missing.md)\n", encoding="utf-8")

    report = json.loads(run_audit(project, "--strict").stdout)

    assert set(report["measurements"]) == {"AGENTS.md"}


def test_audit_accepts_markdown_link_title(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        '[guide](docs/guide.md "Guide")\n', encoding="utf-8"
    )
    guide = tmp_path / "docs/guide.md"
    guide.parent.mkdir()
    guide.write_text("# Guide\n", encoding="utf-8")

    report = json.loads(run_audit(tmp_path, "--strict").stdout)

    assert report["summary"]["error_count"] == 0


def test_audit_rejects_local_link_that_escapes_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.md").write_text("# Outside\n", encoding="utf-8")
    (project / "AGENTS.md").write_text("[outside](../outside.md)\n", encoding="utf-8")

    result = run_audit(project, "--strict")
    report = json.loads(result.stdout)

    assert result.returncode == 1
    assert any(item["code"] == "LOCAL_LINK_ESCAPES_ROOT" for item in report["findings"])


def test_audit_reports_broken_agent_compatibility_symlink(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").symlink_to("missing.md")

    result = run_audit(tmp_path, "--strict")
    report = json.loads(result.stdout)

    assert result.returncode == 1
    assert report["agent_source"]["status"] == "conflict"
    assert any(
        item["code"] == "AGENT_AUTHORITY_CONFLICT" for item in report["findings"]
    )
