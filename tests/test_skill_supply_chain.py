"""Skill supply-chain registry checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.skill_supply_chain import (  # noqa: E402
    DEFAULT_REGISTRY,
    DEFAULT_TARGETS,
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
    snapshot_output_path,
    strip_jsonc_comments,
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
    }


def test_snapshot_output_path_uses_registry_snapshot_root(tmp_path: Path) -> None:
    registry = load_registry(ROOT / "agent-skills/registry/sources.jsonc")

    path = snapshot_output_path(registry, tmp_path, "before move", "2026-07-10T120000Z")

    assert path == tmp_path / ".agent-state/skill-snapshots/2026-07-10T120000Z-before-move.json"


def test_distribute_apply_rejects_devspace_worktree_by_default():
    with pytest.raises(RegistryError, match="DevSpace worktree"):
        _assert_safe_apply_root(Path.home() / ".devspace" / "worktrees" / "template-example")


def test_distribute_apply_allows_real_checkout_paths():
    _assert_safe_apply_root(ROOT)


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
        "pi",
        "reasonix",
        "antigravity",
        "cross-agent",
    )
    assert knowledge.source_path == Path("agent-skills/local/global/knowledge-lifecycle-manager")

    python_skill = registry.skills[("local-product-strategy", "python-data-analysis")]
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
    skill_dir = tmp_path / "agent-skills/local/mac-bootstrap/example-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: other-skill\ndescription: Bad\n---\n\n# Bad\n",
        encoding="utf-8",
    )

    errors = validate_skill_dir(skill_dir, "example-skill")

    assert any("frontmatter name mismatch" in error for error in errors)


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


def test_skills_sh_command_uses_specific_skill_and_universal_agent():
    registry = load_registry(DEFAULT_REGISTRY)
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
    registry = load_registry(DEFAULT_REGISTRY)
    skill = registry.skills[("anthropic-skills", "pdf")]

    cmd = build_skills_sh_fetch_command(skill)

    assert cmd[3] == "anthropics/skills"
    assert cmd[5] == "pdf"
    assert "--agent" in cmd
    assert "universal" in cmd
    assert "--copy" in cmd


def test_baoyu_and_guizang_sources_use_skills_sh_urls():
    registry = load_registry(DEFAULT_REGISTRY)

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
    registry = load_registry(DEFAULT_REGISTRY)

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

    handoff = registry.skills[("mattpocock-skills", "handoff")]
    assert handoff.scope == "global"
    assert handoff.distribution_state == "enabled"
    assert handoff.agents == (
        "claude",
        "codex",
        "opencode",
        "pi",
        "reasonix",
        "antigravity",
        "cross-agent",
    )

    assert registry.skills[("mattpocock-skills", "write-a-skill")].distribution_state == "staged"
    assert registry.skills[("mattpocock-skills", "zoom-out")].distribution_state == "staged"


def test_find_skills_command_uses_requested_vercel_skills_url():
    registry = load_registry(DEFAULT_REGISTRY)
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
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

    actions = build_distribution_actions(registry, targets, ROOT)

    codex_actions = [
        action
        for action in actions
        if action.skill_name == "knowledge-lifecycle-manager" and action.target_agent == "codex"
    ]
    assert codex_actions
    assert codex_actions[0].action == "link-dir"
    assert codex_actions[0].source == ROOT / "agent-skills/local/global/knowledge-lifecycle-manager"


def test_project_internal_skill_distributes_only_to_project_view():
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

    actions = build_distribution_actions(registry, targets, ROOT)

    project_actions = [action for action in actions if action.skill_name == "python-data-analysis"]
    assert len(project_actions) == 1
    assert project_actions[0].target_agent is None
    assert project_actions[0].target_path.as_posix().endswith(
        "/work/projects/product_strategy/.agents/skills/python-data-analysis"
    )


def test_project_external_shadow_skill_distributes_from_checked_in_shadow():
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

    actions = build_distribution_actions(registry, targets, ROOT)

    baoyu = [action for action in actions if action.skill_name == "baoyu-diagram"]
    assert len(baoyu) == 1
    assert baoyu[0].target_agent is None
    assert baoyu[0].source == ROOT / "agent-skills/local/shadows/baoyu/baoyu-diagram"
    assert baoyu[0].target_path.as_posix().endswith(
        "/work/projects/product_strategy/.agents/skills/baoyu-diagram"
    )


def test_reasonix_distribution_uses_flat_md():
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

    actions = build_distribution_actions(registry, targets, ROOT)

    reasonix = [
        action
        for action in actions
        if action.skill_name == "knowledge-lifecycle-manager" and action.target_agent == "reasonix"
    ][0]
    assert reasonix.action == "copy-flat-md"
    assert reasonix.target_path.name == "knowledge-lifecycle-manager.md"


def _filter_reconcile_actions(actions, *, surface=None, skill=None):
    if surface:
        actions = [action for action in actions if action.surface == surface]
    if skill:
        actions = [action for action in actions if action.skill_name == skill]
    return actions


def test_reconcile_actions_include_stale_entries_but_not_enabled_targets(tmp_path: Path):
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

    codex_root = tmp_path / "codex-skills"
    codex_root.mkdir()
    (codex_root / "stale-skill").symlink_to(
        ROOT / "agent-skills/local/global/knowledge-lifecycle-manager"
    )
    (codex_root / "knowledge-lifecycle-manager").symlink_to(
        ROOT / "agent-skills/local/global/knowledge-lifecycle-manager"
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

    filtered = _filter_reconcile_actions(actions, surface="global", skill="stale-skill")
    assert [action.skill_name for action in filtered] == ["stale-skill"]
    assert filtered[0].surface == "global"


def test_reconcile_skips_real_directories(tmp_path: Path):
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

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
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

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
          "version": 2,
          "paths": {{"local_root": "agent-skills/local", "quarantine_root": "agent-skills/external/quarantine", "lockfile": ".agent-state/skills-lock.json", "run_log_root": ".agent-state/skill-sync-runs", "snapshot_root": ".agent-state/skill-snapshots"}},
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
    skill_dir = tmp_path / "agent-skills/external/quarantine/external/scripted"
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
    skill_dir = tmp_path / "agent-skills/external/quarantine/external/safe"
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
