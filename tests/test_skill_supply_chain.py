"""Skill supply-chain registry checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.skill_supply_chain import (  # noqa: E402
    RegistryError,
    _assert_safe_apply_root,
    build_distribution_actions,
    build_distribution_snapshot,
    build_reconcile_actions,
    build_skills_sh_fetch_command,
    compare_distribution_snapshots,
    evaluate_gate,
    find_unmanaged_skill_dirs,
    inspect_skill_content,
    load_registry,
    load_targets,
    strip_jsonc_comments,
    validate_skill_dir,
)


def test_distribute_apply_rejects_devspace_worktree_by_default():
    with pytest.raises(RegistryError, match="DevSpace worktree"):
        _assert_safe_apply_root(Path("/Users/suai/.devspace/worktrees/template-example"))


def test_distribute_apply_allows_real_checkout_paths():
    _assert_safe_apply_root(Path("/Users/suai/work/config/mac-bootstrap/template"))


def test_strip_jsonc_comments_preserves_urls_and_strings():
    raw = '''{
      // comment
      "url": "https://github.com/vercel-labs/agent-skills",
      "text": "keep // inside string",
      "path": "agent/skills/quarantine" // trailing comment
    }'''

    stripped = strip_jsonc_comments(raw)

    assert "comment" not in stripped
    assert "trailing comment" not in stripped
    assert "https://github.com/vercel-labs/agent-skills" in stripped
    assert "keep // inside string" in stripped


def test_registry_contains_external_and_internal_examples():
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")

    vercel = registry.skills[("vercel-agent-skills", "web-design-guidelines")]
    assert vercel.source_type == "external"
    assert vercel.ref == "vercel-labs/agent-skills"
    assert vercel.quarantine_path == Path(
        "agent/skills/quarantine/vercel-agent-skills/web-design-guidelines"
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

    knowledge = registry.skills[("local-personal", "knowledge-lifecycle-manager")]
    assert knowledge.source_type == "internal"
    assert knowledge.scope == "global"
    assert knowledge.agents == (
        "claude",
        "codex",
        "opencode",
        "pi",
        "reasonix",
        "antigravity",
        "cross-agent",
    )
    assert knowledge.source_path == Path("agent/skills/personal/knowledge-lifecycle-manager")

    python_skill = registry.skills[("local-personal", "python-data-analysis")]
    assert python_skill.scope == "project"
    assert python_skill.projects == ("product_strategy",)

    baoyu = registry.skills[("baoyu-skills", "baoyu-diagram")]
    assert baoyu.source_type == "external"
    assert baoyu.ref == "https://github.com/JimLiu/baoyu-skills"
    assert baoyu.local_shadow_path == Path("agent/skills/personal/baoyu-diagram")

    guizang = registry.skills[("guizang-ppt-skill", "guizang-ppt-skill")]
    assert guizang.source_type == "external"
    assert guizang.ref == "https://github.com/op7418/guizang-ppt-skill"
    assert guizang.local_shadow_path == Path("agent/skills/personal/guizang-ppt-skill")

    caveman = registry.skills[("mattpocock-skills", "caveman")]
    assert caveman.source_type == "external"
    assert caveman.ref == "https://github.com/mattpocock/skills"
    assert caveman.local_shadow_path == Path("agent/skills/personal/caveman")
    assert ("local-personal", "caveman") not in registry.skills

    langgpt = registry.skills[("langgpt", "langgpt-prompt-writer")]
    assert langgpt.source_type == "external"
    assert langgpt.fetcher == "manual"
    assert langgpt.distribution_state == "staged"
    assert langgpt.local_shadow_path == Path("agent/skills/personal/langgpt-prompt-writer")

    qiaomu = registry.skills[("qiaomu-goal-meta-skill", "qiaomu-goal-meta-skill")]
    assert qiaomu.source_type == "external"
    assert qiaomu.ref == "joeseesun/qiaomu-goal-meta-skill"
    assert qiaomu.local_shadow_path == Path("agent/skills/personal/qiaomu-goal-meta-skill")


def test_registry_covers_current_internal_skill_sources():
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")
    registered_sources = {
        source
        for skill in registry.skills.values()
        for source in (skill.source_path, skill.local_shadow_path)
        if source is not None
    }

    personal_sources = {
        path.relative_to(ROOT)
        for path in (ROOT / "agent/skills/personal").iterdir()
        if (path / "SKILL.md").is_file()
    }
    standalone_daily_tagger = Path("agent/skills/daily-tagger")

    assert personal_sources <= registered_sources
    assert standalone_daily_tagger in registered_sources


def test_skill_targets_match_current_production_distribution():
    manifest = json.loads((ROOT / "agent/agent-manifest.json").read_text(encoding="utf-8"))
    targets = load_targets(ROOT / "agent/skill-targets.jsonc")

    expected = {
        "claude": (manifest["agents"]["claude"]["paths"]["skills"], "directory", "symlink"),
        "codex": (manifest["agents"]["codex"]["paths"]["skills"], "directory", "symlink"),
        "opencode": (manifest["agents"]["opencode"]["paths"]["skills"], "directory", "symlink"),
        "pi": (manifest["agents"]["pi"]["paths"]["skills"], "directory", "symlink"),
        "antigravity": (
            manifest["agents"]["antigravity"]["paths"]["skills"],
            "directory",
            "symlink",
        ),
        "cross-agent": (manifest["shared"]["cross_agent_skills_dir"], "directory", "symlink"),
        "reasonix": (manifest["agents"]["reasonix"]["paths"]["skills"], "flat-md", "copy"),
    }

    assert set(targets) == set(expected)
    for name, (path, fmt, strategy) in expected.items():
        assert targets[name].path.as_posix() == path
        assert targets[name].format == fmt
        assert targets[name].strategy == strategy


def test_validate_skill_dir_requires_matching_name(tmp_path: Path):
    skill_dir = tmp_path / "agent/skills/personal/example-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: other-skill\ndescription: Bad\n---\n\n# Bad\n",
        encoding="utf-8",
    )

    errors = validate_skill_dir(skill_dir, "example-skill")

    assert any("frontmatter name mismatch" in error for error in errors)


def test_find_unmanaged_skill_dirs_reports_unregistered_internal_source(tmp_path: Path):
    (tmp_path / "agent/skills/personal/managed").mkdir(parents=True)
    (tmp_path / "agent/skills/personal/managed/SKILL.md").write_text(
        "---\nname: managed\ndescription: Managed\n---\n\n# Managed\n",
        encoding="utf-8",
    )
    (tmp_path / "agent/skills/personal/orphan").mkdir(parents=True)
    (tmp_path / "agent/skills/personal/orphan/SKILL.md").write_text(
        "---\nname: orphan\ndescription: Orphan\n---\n\n# Orphan\n",
        encoding="utf-8",
    )
    registry_path = tmp_path / "skills-sources.jsonc"
    registry_path.write_text(
        '''{
          "version": 1,
          "paths": {"internal_root": "agent/skills/personal", "standalone_internal_root": "agent/skills", "quarantine_root": "agent/skills/quarantine"},
          "defaults": {"internal": {"scope": "project", "audit": {"required": false}, "gate": {"approved": true}}},
          "projects": {"mac-bootstrap": {"skills_dir": "${HOME}/work/config/mac-bootstrap/.agents/skills"}},
          "sources": {"local": {"type": "internal", "path": "agent/skills/personal", "skills": {"managed": {"projects": ["mac-bootstrap"]}}}}
        }''',
        encoding="utf-8",
    )
    registry = load_registry(registry_path)

    unmanaged = find_unmanaged_skill_dirs(registry, tmp_path)

    assert unmanaged == [tmp_path / "agent/skills/personal/orphan"]


def test_skills_sh_command_uses_specific_skill_and_universal_agent():
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")
    skill = registry.skills[("vercel-agent-skills", "web-design-guidelines")]

    cmd = build_skills_sh_fetch_command(skill)

    assert cmd == [
        "npx",
        "skills",
        "add",
        "vercel-labs/agent-skills",
        "--skill",
        "web-design-guidelines",
        "--agent",
        "universal",
        "--copy",
        "--yes",
    ]


def test_anthropic_pdf_command_uses_same_quarantine_fetch_shape():
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")
    skill = registry.skills[("anthropic-skills", "pdf")]

    cmd = build_skills_sh_fetch_command(skill)

    assert cmd[3] == "anthropics/skills"
    assert cmd[5] == "pdf"
    assert "--agent" in cmd
    assert "universal" in cmd
    assert "--copy" in cmd


def test_baoyu_and_guizang_sources_use_skills_sh_urls():
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")

    baoyu_cmd = build_skills_sh_fetch_command(registry.skills[("baoyu-skills", "baoyu-infographic")])
    guizang_cmd = build_skills_sh_fetch_command(
        registry.skills[("guizang-ppt-skill", "guizang-ppt-skill")]
    )

    assert baoyu_cmd[:6] == [
        "npx",
        "skills",
        "add",
        "https://github.com/JimLiu/baoyu-skills",
        "--skill",
        "baoyu-infographic",
    ]
    assert guizang_cmd[:6] == [
        "npx",
        "skills",
        "add",
        "https://github.com/op7418/guizang-ppt-skill",
        "--skill",
        "guizang-ppt-skill",
    ]


def test_mattpocock_commands_include_skills_sh_page_backed_skills():
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")

    for name in ("diagnose", "write-a-skill", "zoom-out"):
        cmd = build_skills_sh_fetch_command(registry.skills[("mattpocock-skills", name)])
        assert cmd[:6] == [
            "npx",
            "skills",
            "add",
            "https://github.com/mattpocock/skills",
            "--skill",
            name,
        ]

    assert registry.skills[("mattpocock-skills", "diagnose")].distribution_state == "enabled"
    assert registry.skills[("mattpocock-skills", "write-a-skill")].distribution_state == "staged"
    assert registry.skills[("mattpocock-skills", "zoom-out")].distribution_state == "staged"


def test_find_skills_command_uses_requested_vercel_skills_url():
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")
    skill = registry.skills[("vercel-skills", "find-skills")]

    cmd = build_skills_sh_fetch_command(skill)

    assert cmd == [
        "npx",
        "skills",
        "add",
        "https://github.com/vercel-labs/skills",
        "--skill",
        "find-skills",
        "--agent",
        "universal",
        "--copy",
        "--yes",
    ]


def test_global_internal_skill_distributes_to_configured_agents():
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")
    targets = load_targets(ROOT / "agent/skill-targets.jsonc")

    actions = build_distribution_actions(registry, targets, ROOT)

    codex_actions = [
        action
        for action in actions
        if action.skill_name == "knowledge-lifecycle-manager" and action.target_agent == "codex"
    ]
    assert codex_actions
    assert codex_actions[0].action == "link-dir"
    assert codex_actions[0].source == ROOT / "agent/skills/personal/knowledge-lifecycle-manager"


def test_project_internal_skill_distributes_only_to_project_view():
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")
    targets = load_targets(ROOT / "agent/skill-targets.jsonc")

    actions = build_distribution_actions(registry, targets, ROOT)

    project_actions = [action for action in actions if action.skill_name == "python-data-analysis"]
    assert len(project_actions) == 1
    assert project_actions[0].target_agent is None
    assert project_actions[0].target_path.as_posix().endswith(
        "/work/projects/product_strategy/.agents/skills/python-data-analysis"
    )


def test_reasonix_distribution_uses_flat_md():
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")
    targets = load_targets(ROOT / "agent/skill-targets.jsonc")

    actions = build_distribution_actions(registry, targets, ROOT)

    reasonix = [
        action
        for action in actions
        if action.skill_name == "knowledge-lifecycle-manager" and action.target_agent == "reasonix"
    ][0]
    assert reasonix.action == "copy-flat-md"
    assert reasonix.target_path.name == "knowledge-lifecycle-manager.md"


def test_reconcile_actions_include_stale_entries_but_not_enabled_targets(tmp_path: Path):
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")
    targets = load_targets(ROOT / "agent/skill-targets.jsonc")

    codex_root = tmp_path / "codex-skills"
    codex_root.mkdir()
    (codex_root / "stale-skill").symlink_to(ROOT / "agent/skills/personal/knowledge-lifecycle-manager")
    (codex_root / "knowledge-lifecycle-manager").symlink_to(
        ROOT / "agent/skills/personal/knowledge-lifecycle-manager"
    )
    targets = {
        **targets,
        "codex": type(targets["codex"])(
            agent="codex",
            path=codex_root,
            format="directory",
            strategy="symlink",
        ),
    }

    actions = build_reconcile_actions(registry, targets, ROOT)

    names = {(action.target_name, action.skill_name, action.action) for action in actions}
    assert ("codex", "stale-skill", "remove-symlink") in names
    assert not any(action.skill_name == "knowledge-lifecycle-manager" for action in actions)


def test_reconcile_skips_real_directories(tmp_path: Path):
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")
    targets = load_targets(ROOT / "agent/skill-targets.jsonc")

    codex_root = tmp_path / "codex-skills"
    (codex_root / "stale-real-dir").mkdir(parents=True)
    targets = {
        **targets,
        "codex": type(targets["codex"])(
            agent="codex",
            path=codex_root,
            format="directory",
            strategy="symlink",
        ),
    }

    actions = build_reconcile_actions(registry, targets, ROOT)

    assert any(
        action.skill_name == "stale-real-dir" and action.action == "skip-real-path" for action in actions
    )


def test_snapshot_captures_global_and_project_targets():
    registry = load_registry(ROOT / "agent/skills-sources.jsonc")
    targets = load_targets(ROOT / "agent/skill-targets.jsonc")

    snapshot = build_distribution_snapshot(registry, targets, ROOT, label="test")

    assert snapshot["schema_version"] == 1
    assert "claude" in snapshot["global_targets"]
    assert "mac-bootstrap" in snapshot["project_targets"]
    assert snapshot["global_targets"]["reasonix"]["format"] == "flat-md"
    assert "global_total_entries" in snapshot["counts"]
    assert "project_total_entries" in snapshot["counts"]


def test_snapshot_diff_reports_missing_added_and_changed_items():
    before = {
        "global_targets": {
            "codex": {
                "skills": {
                    "keep": {"skill_md_sha256": "a", "link_target": "old"},
                    "missing": {"skill_md_sha256": "b", "link_target": "same"},
                }
            }
        },
        "project_targets": {},
    }
    after = {
        "global_targets": {
            "codex": {
                "skills": {
                    "keep": {"skill_md_sha256": "a", "link_target": "new"},
                    "added": {"skill_md_sha256": "c", "link_target": "same"},
                }
            }
        },
        "project_targets": {},
    }

    diff = compare_distribution_snapshots(before, after)

    assert diff["global_targets"]["missing"] == ["codex/missing"]
    assert diff["global_targets"]["added"] == ["codex/added"]
    assert diff["global_targets"]["changed"] == ["codex/keep"]


def write_registry_for_external(tmp_path: Path, skill: str, approved_hash: str | None = None) -> Path:
    approval = "false" if approved_hash is None else "true"
    hash_line = "" if approved_hash is None else f', "approved_hash": "{approved_hash}"'
    registry_path = tmp_path / "skills-sources.jsonc"
    registry_path.write_text(
        f'''{{
          "version": 1,
          "paths": {{"internal_root": "agent/skills/personal", "standalone_internal_root": "agent/skills", "quarantine_root": "agent/skills/quarantine"}},
          "defaults": {{
            "external": {{"scope": "global", "agents": ["codex"], "audit": {{"required": true, "allow_unaudited": false, "allow_scripts": false}}, "gate": {{"manual_approval": true, "approved": {approval}{hash_line}}}}},
            "internal": {{"scope": "project", "audit": {{"required": false}}, "gate": {{"approved": true}}}}
          }},
          "projects": {{"mac-bootstrap": {{"skills_dir": "${{HOME}}/work/config/mac-bootstrap/.agents/skills"}}}},
          "sources": {{"external": {{"type": "external", "fetcher": "skills.sh", "ref": "owner/repo", "skills": {{"{skill}": {{}}}}}}}}
        }}''',
        encoding="utf-8",
    )
    return registry_path


def test_gate_blocks_external_skill_with_scripts_when_scripts_not_allowed(tmp_path: Path):
    skill_dir = tmp_path / "agent/skills/quarantine/external/scripted"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scripted\ndescription: Has scripts\n---\n\n# Scripted\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts/run.sh").write_text("echo hi\n", encoding="utf-8")
    skill = load_registry(write_registry_for_external(tmp_path, "scripted")).skills[("external", "scripted")]

    decision = evaluate_gate(skill, inspect_skill_content(skill_dir), audit=None)

    assert decision.allowed is False
    assert "scripts present but audit.allow_scripts is false" in decision.reasons


def test_gate_requires_approval_hash_to_match_current_content(tmp_path: Path):
    skill_dir = tmp_path / "agent/skills/quarantine/external/safe"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: safe\ndescription: Safe\n---\n\n# Safe\n",
        encoding="utf-8",
    )
    current_hash = inspect_skill_content(skill_dir).content_hash
    skill = load_registry(write_registry_for_external(tmp_path, "safe", approved_hash="old")).skills[("external", "safe")]

    decision = evaluate_gate(skill, inspect_skill_content(skill_dir), audit=None)

    assert current_hash != "old"
    assert decision.allowed is False
    assert decision.approved_version_matches is False
