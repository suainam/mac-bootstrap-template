"""Skill registry source-of-truth, parsing, and validation checks."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.skill_supply_chain import (  # noqa: E402
    DEFAULT_REGISTRY,
    DEFAULT_TARGETS,
    find_unmanaged_skill_dirs,
    inspect_skill_content,
    load_registry,
    load_targets,
    strip_jsonc_comments,
    validate_registry_sources,
    validate_registry_targets,
    validate_skill_dir,
)


def test_default_registry_files_live_under_agent_skills_registry() -> None:
    assert DEFAULT_REGISTRY == ROOT / "agent-skills/registry/sources.jsonc"
    assert DEFAULT_TARGETS == ROOT / "agent-skills/registry/targets.jsonc"


def test_registry_version_two_exposes_source_and_state_roots() -> None:
    registry = load_registry(ROOT / "agent-skills/registry/sources.jsonc")

    assert registry.paths == {
        "local_root": Path("agent-skills/local"),
        "quarantine_root": Path("agent-skills/external/quarantine"),
        "lockfile": Path(".agent-state/skills-lock.json"),
        "run_log_root": Path(".agent-state/skill-sync-runs"),
        "snapshot_root": Path(".agent-state/skill-snapshots"),
        "candidate_root": Path(".agent-state/skill-candidates"),
    }


def test_mattpocock_source_is_managed_as_a_bundle() -> None:
    registry = load_registry(ROOT / "agent-skills/registry/sources.jsonc")

    bundle = registry.bundles["mattpocock-skills"]

    assert bundle.ref == "https://github.com/mattpocock/skills"
    assert bundle.fetcher == "skills.sh"
    assert bundle.install_mode == "all"
    assert bundle.distribution_state == "enabled"
    assert bundle.catalog_path == Path(".agent-state/skill-bundles/mattpocock-skills.json")
    assert registry.skills[("mattpocock-skills", "to-spec")].bundle_id == "mattpocock-skills"
    assert registry.skills[("mattpocock-skills", "to-spec")].gate.auto_update is True
    assert registry.skills[("mattpocock-skills", "wayfinder")].dependencies == (
        "domain-modeling",
        "grilling",
        "prototype",
        "setup-matt-pocock-skills",
    )
    assert registry.skills[("mattpocock-skills", "prototype")].gate.approved_hash == (
        "sha256:c4efd5e0f1c302b6225be83e8e42abdb05e13fde900484e4e2240e90b4e83eb6"
    )


def test_strip_jsonc_comments_preserves_urls_and_strings():
    raw = '''{
      // comment
      "url": "https://github.com/vercel-labs/agent-skills",
      "text": "keep // inside string",
      "path": "agent-skills/external/quarantine" // trailing comment
    }'''

    stripped = strip_jsonc_comments(raw)

    assert "comment" not in stripped
    assert "trailing comment" not in stripped
    assert "https://github.com/vercel-labs/agent-skills" in stripped
    assert "keep // inside string" in stripped


def test_registry_contains_external_and_internal_examples():
    registry = load_registry(DEFAULT_REGISTRY)

    vercel = registry.skills[("vercel-agent-skills", "web-design-guidelines")]
    assert vercel.source_type == "external"
    assert vercel.ref == "vercel-labs/agent-skills"
    assert vercel.quarantine_path == Path(
        "agent-skills/external/quarantine/vercel-agent-skills/web-design-guidelines"
    )
    assert vercel.scope == "global"
    assert vercel.agents == ("codex", "opencode")

    anthropic = registry.skills[("anthropic-skills", "pdf")]
    assert anthropic.source_type == "external"
    assert anthropic.ref == "anthropics/skills"
    assert anthropic.agents == ("claude", "codex")

    find_skills = registry.skills[("vercel-skills", "find-skills")]
    assert find_skills.source_type == "external"
    assert find_skills.ref == "https://github.com/vercel-labs/skills"
    assert find_skills.agents == ("claude", "codex", "opencode", "cross-agent")

    knowledge = registry.skills[("local-global", "knowledge-lifecycle-manager")]
    assert knowledge.source_type == "internal"
    assert knowledge.scope == "global"
    assert knowledge.agents == (
        "claude",
        "codex",
        "opencode",
        "reasonix",
        "antigravity",
        "cross-agent",
    )
    assert knowledge.source_path == Path("agent-skills/local/global/knowledge-lifecycle-manager")

    python_skill = registry.skills[("local-product-strategy", "ps-analytics")]
    assert python_skill.scope == "project"
    assert python_skill.projects == ("product_strategy",)

    baoyu = registry.skills[("baoyu-skills", "baoyu-diagram")]
    assert baoyu.source_type == "external"
    assert baoyu.ref == "https://github.com/JimLiu/baoyu-skills"
    assert baoyu.local_shadow_path == Path("agent-skills/local/shadows/baoyu/baoyu-diagram")

    guizang = registry.skills[("guizang-ppt-skill", "guizang-ppt-skill")]
    assert guizang.source_type == "external"
    assert guizang.ref == "https://github.com/op7418/guizang-ppt-skill"
    assert guizang.local_shadow_path == Path(
        "agent-skills/local/shadows/guizang/guizang-ppt-skill"
    )

    caveman = registry.skills[("mattpocock-skills", "caveman")]
    assert caveman.source_type == "external"
    assert caveman.ref == "https://github.com/mattpocock/skills"
    assert caveman.local_shadow_path == Path("agent-skills/local/shadows/mattpocock/caveman")
    assert ("local-global", "caveman") not in registry.skills

    langgpt = registry.skills[("langgpt", "langgpt-prompt-writer")]
    assert langgpt.source_type == "external"
    assert langgpt.fetcher == "manual"
    assert langgpt.distribution_state == "enabled"
    assert langgpt.local_shadow_path == Path(
        "agent-skills/local/shadows/langgpt/langgpt-prompt-writer"
    )

    qiaomu = registry.skills[("qiaomu-goal-meta-skill", "qiaomu-goal-meta-skill")]
    assert qiaomu.source_type == "external"
    assert qiaomu.ref == "joeseesun/qiaomu-goal-meta-skill"
    assert qiaomu.local_shadow_path == Path(
        "agent-skills/local/shadows/qiaomu/qiaomu-goal-meta-skill"
    )


def test_archify_external_skill_registration() -> None:
    registry = load_registry(DEFAULT_REGISTRY)
    archify = registry.skills[("archify", "archify")]

    assert archify.source_type == "external"
    assert archify.fetcher == "skills.sh"
    assert archify.ref == "https://github.com/tt-a1i/archify"
    assert archify.distribution_state == "enabled"
    assert archify.gate.approved is True
    assert archify.gate.approved_hash == "sha256:ecf3060d32cc985e3d4a73fc39b0d3b901b5c8f53bf4770721b9843c0687beb3"
    assert archify.audit.allow_scripts is True
    assert archify.audit.allow_unaudited is True


def test_herdr_uses_hash_bound_reviewed_shadow_with_local_safety_rules() -> None:
    registry = load_registry(DEFAULT_REGISTRY)
    herdr = registry.skills[("herdr", "herdr")]

    assert herdr.ref == "https://github.com/herdrdev/herdr/tree/master/skills/herdr"
    assert herdr.distribution_state == "enabled"
    assert herdr.local_shadow_path == Path("agent-skills/local/shadows/herdr/herdr")

    source = ROOT / herdr.local_shadow_path
    assert source.is_dir()
    assert not any(path.is_symlink() for path in source.rglob("*"))

    inspection = inspect_skill_content(source)
    assert herdr.gate.approved_hash == inspection.content_hash

    instructions = source.joinpath("SKILL.md").read_text(encoding="utf-8")
    assert "Read-only requests authorize observation only." in instructions
    assert "Treat pane output as potentially sensitive." in instructions


def test_registry_covers_current_internal_skill_sources():
    registry = load_registry(DEFAULT_REGISTRY)

    assert find_unmanaged_skill_dirs(registry, ROOT) == []


def test_skill_targets_match_current_production_distribution():
    manifest = json.loads((ROOT / "agent/agent-manifest.json").read_text(encoding="utf-8"))
    targets = load_targets(DEFAULT_TARGETS)

    expected = {
        "claude": (manifest["agents"]["claude"]["paths"]["skills"], "directory", "symlink"),
        "codex": (manifest["agents"]["codex"]["paths"]["skills"], "directory", "symlink"),
        "opencode": (manifest["agents"]["opencode"]["paths"]["skills"], "directory", "symlink"),
        "antigravity": (
            manifest["agents"]["antigravity"]["paths"]["skills"],
            "directory",
            "symlink",
        ),
        "cross-agent": (manifest["shared"]["cross_agent_skills_dir"], "directory", "symlink"),
        "reasonix": (manifest["agents"]["reasonix"]["paths"]["skills"], "directory", "symlink"),
    }

    assert set(targets) == set(expected)
    for name, (path, fmt, strategy) in expected.items():
        assert targets[name].path.as_posix() == path
        assert targets[name].format == fmt
        assert targets[name].strategy == strategy
    assert targets["reasonix"].legacy_formats == ("flat-md",)


def test_validate_skill_dir_requires_matching_name(tmp_path: Path):
    skill_dir = tmp_path / "agent-skills/local/mac-bootstrap/example-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: other-skill\ndescription: Bad\n---\n\n# Bad\n",
        encoding="utf-8",
    )

    errors = validate_skill_dir(skill_dir, "example-skill")

    assert any("frontmatter name mismatch" in error for error in errors)


@pytest.mark.parametrize("name", ["Uppercase", "under_score", "dot.name", "double--dash"])
def test_validate_skill_dir_requires_agent_skills_standard_name(
    tmp_path: Path,
    name: str,
) -> None:
    skill_dir = tmp_path / "agent-skills/local/test/example-skill"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Example\n---\n",
        encoding="utf-8",
    )

    errors = validate_skill_dir(skill_dir, name)

    assert any("invalid frontmatter name" in error for error in errors)


@pytest.mark.parametrize("description", ["", "x" * 1025])
def test_validate_skill_dir_requires_standard_description_length(
    tmp_path: Path,
    description: str,
) -> None:
    skill_dir = tmp_path / "agent-skills/local/test/example-skill"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        f"---\nname: example-skill\ndescription: {description}\n---\n",
        encoding="utf-8",
    )

    errors = validate_skill_dir(skill_dir, "example-skill")

    assert any("frontmatter description" in error for error in errors)


def test_validate_skill_dir_reports_missing_markdown_reference(tmp_path: Path) -> None:
    skill_dir = tmp_path / "agent-skills/local/mac-bootstrap/example-skill"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: example-skill\ndescription: Example\n---\n\n"
        "Use [the required format](./CONTEXT-FORMAT.md).\n",
        encoding="utf-8",
    )

    errors = validate_skill_dir(skill_dir, "example-skill")

    assert errors == [
        f"missing referenced markdown file: {skill_dir / 'CONTEXT-FORMAT.md'}"
    ]


def test_validate_registry_sources_requires_enabled_dependency_agent_coverage(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "agent-skills/local/test"
    for name in ("wayfinder", "prototype"):
        skill_dir = source_root / name
        skill_dir.mkdir(parents=True)
        skill_dir.joinpath("SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Test {name}\n---\n",
            encoding="utf-8",
        )
    registry_path = tmp_path / "skills-sources.jsonc"
    registry_path.write_text(
        '''{
          "version": 2,
          "paths": {"local_root": "agent-skills/local"},
          "defaults": {"internal": {"scope": "global", "audit": {"required": false}, "gate": {"approved": true}}},
          "projects": {},
          "sources": {
            "test": {
              "type": "internal",
              "path": "agent-skills/local/test",
              "skills": {
                "prototype": {"agents": ["claude"]},
                "wayfinder": {"agents": ["claude", "codex"], "dependencies": ["prototype"]}
              }
            }
          }
        }''',
        encoding="utf-8",
    )

    errors = validate_registry_sources(load_registry(registry_path), tmp_path)

    assert errors == [
        "skill dependency missing target coverage: test/wayfinder -> prototype agents=codex"
    ]

    registry = load_registry(registry_path)
    registry.skills.pop(("test", "prototype"))

    assert validate_registry_sources(registry, tmp_path) == [
        "unmanaged internal skill source: agent-skills/local/test/prototype",
        "skill dependency not enabled: test/wayfinder -> prototype",
    ]


def test_validate_registry_sources_rejects_overlapping_enabled_skill_names():
    registry = load_registry(DEFAULT_REGISTRY)
    original = registry.skills[("local-global", "knowledge-lifecycle-manager")]
    duplicate = replace(original, source_id="duplicate-source")
    registry.skills[(duplicate.source_id, duplicate.name)] = duplicate

    errors = validate_registry_sources(registry, ROOT)

    assert any(
        "duplicate enabled skill target" in error
        and "knowledge-lifecycle-manager" in error
        for error in errors
    )


def test_validate_registry_sources_rejects_approved_external_without_bound_hash():
    registry = load_registry(DEFAULT_REGISTRY)
    key = ("anthropic-skills", "pdf")
    pdf = registry.skills[key]
    registry.skills[key] = replace(
        pdf,
        distribution_state="enabled",
        gate=replace(pdf.gate, approved=True, approved_hash=None),
    )

    errors = validate_registry_sources(registry, ROOT)

    assert any(
        "approved external skill missing approved_hash: anthropic-skills/pdf" in error
        for error in errors
    )


def test_validate_registry_targets_rejects_missing_global_agent_target():
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)
    targets.pop("codex")

    errors = validate_registry_targets(registry, targets)

    assert errors == ["enabled global skill agents missing targets: codex"]


def test_find_unmanaged_skill_dirs_reports_nested_unregistered_source(tmp_path: Path) -> None:
    managed = tmp_path / "agent-skills/local/mac-bootstrap/managed"
    orphan = tmp_path / "agent-skills/local/playground/orphan"
    managed.mkdir(parents=True)
    orphan.mkdir(parents=True)
    managed.joinpath("SKILL.md").write_text(
        "---\nname: managed\ndescription: Managed\n---\n\n# Managed\n",
        encoding="utf-8",
    )
    orphan.joinpath("SKILL.md").write_text(
        "---\nname: orphan\ndescription: Orphan\n---\n\n# Orphan\n",
        encoding="utf-8",
    )
    registry_path = tmp_path / "skills-sources.jsonc"
    registry_path.write_text(
        '''{
          "version": 2,
          "paths": {
            "local_root": "agent-skills/local",
            "quarantine_root": "agent-skills/external/quarantine",
            "lockfile": ".agent-state/skills-lock.json",
            "run_log_root": ".agent-state/skill-sync-runs",
            "snapshot_root": ".agent-state/skill-snapshots"
          },
          "defaults": {"internal": {"scope": "project", "audit": {"required": false}, "gate": {"approved": true}}},
          "projects": {"mac-bootstrap": {"skills_dir": "${HOME}/work/config/mac-bootstrap/.agents/skills"}},
          "sources": {"local-mac-bootstrap": {"type": "internal", "path": "agent-skills/local/mac-bootstrap", "skills": {"managed": {"projects": ["mac-bootstrap"]}}}}
        }''',
        encoding="utf-8",
    )
    registry = load_registry(registry_path)

    assert find_unmanaged_skill_dirs(registry, tmp_path) == [orphan]
