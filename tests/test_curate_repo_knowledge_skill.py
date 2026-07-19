from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
SKILL_ROOT = ROOT / "agent-skills/local/global/curate-repo-knowledge"
SKILL_PATH = SKILL_ROOT / "SKILL.md"


def test_skill_is_lean_single_entry_with_two_branches() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    frontmatter = {
        key.strip(): value.strip()
        for key, value in (
            line.split(":", 1)
            for line in text.split("---", 2)[1].strip().splitlines()
        )
    }

    assert set(frontmatter) == {"name", "description"}
    assert frontmatter["name"] == "curate-repo-knowledge"
    assert "cold-start" in frontmatter["description"]
    assert "drift" in frontmatter["description"]
    assert sum(bool(line.strip()) for line in text.splitlines()) <= 80
    assert "TODO" not in text
    assert "bootstrap" in text
    assert "reconcile" in text


def test_skill_progressively_discloses_optional_references() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")

    for name in (
        "bootstrap.md",
        "reconcile.md",
        "evaluation.md",
        "memory-reconcile.md",
        "cross-project.md",
        "audit-report.md",
        "auroraops-example.md",
    ):
        assert f"references/{name}" in text
        assert (SKILL_ROOT / "references" / name).is_file()


def test_optional_cleanup_stays_bounded() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")
    memory = (SKILL_ROOT / "references/memory-reconcile.md").read_text(
        encoding="utf-8"
    )
    cross_project = (SKILL_ROOT / "references/cross-project.md").read_text(
        encoding="utf-8"
    )

    assert "memory" in skill.casefold()
    assert "cross-project" in skill
    assert "explicit authorization" in memory
    assert "docs or Agent authority" in memory
    assert "Do not create a skill" in memory
    assert "declared dependency" in cross_project
    assert "Do not scan unrelated projects" in cross_project


def test_skill_preserves_immutable_mutation_guardrails() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    guardrails = text.split("<!-- IMMUTABLE-GUARDRAILS:START -->", 1)[1].split(
        "<!-- IMMUTABLE-GUARDRAILS:END -->", 1
    )[0]

    assert guardrails.strip().splitlines() == [
        "Require explicit approval to overwrite an authority, delete or rename a file, change hooks, change global agent configuration, resolve an ambiguous conflict, or exceed a persistent-context budget. Keep secrets, private prompts, and raw logs outside reports and generated docs."
    ]


def test_skill_ui_metadata_routes_back_to_single_entry() -> None:
    metadata_text = (SKILL_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")

    assert 'display_name: "Curate Repository Knowledge"' in metadata_text
    short_description = next(
        line.split('"', 2)[1]
        for line in metadata_text.splitlines()
        if "short_description:" in line
    )
    assert 25 <= len(short_description) <= 64
    assert "$curate-repo-knowledge" in metadata_text


def test_skill_reuses_project_native_discovery_and_validation() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert "project-native" in text
    assert "code graph" in text
    assert "language manifests" in text
    assert "fallback" in text

    discovery = text.index("project-native")
    branch = text.index("Select one branch")
    assert discovery < branch
