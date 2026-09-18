"""Skill distribution, reconcile, snapshot, and runtime-hygiene checks."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.skill_supply_chain import (  # noqa: E402
    DEFAULT_REGISTRY,
    DEFAULT_TARGETS,
    DistributionAction,
    RegistryError,
    SkillTarget,
    _assert_safe_apply_root,
    apply_distribution_actions,
    build_distribution_actions,
    build_distribution_snapshot,
    build_reconcile_actions,
    compare_distribution_snapshots,
    filter_reconcile_actions,
    load_registry,
    load_targets,
    main,
    snapshot_output_path,
    validate_runtime_hygiene,
)


def test_disabled_bundle_suppresses_registered_skill_distribution(tmp_path: Path) -> None:
    registry_path = tmp_path / "sources.jsonc"
    raw = (ROOT / "agent-skills/registry/sources.jsonc").read_text(encoding="utf-8").replace(
        '"distribution_state": "enabled",\n        "catalog_path": ".agent-state/skill-bundles/mattpocock-skills.json"',
        '"distribution_state": "disabled",\n        "catalog_path": ".agent-state/skill-bundles/mattpocock-skills.json"',
    )
    registry_path.write_text(raw, encoding="utf-8")
    registry = load_registry(registry_path)

    matt_actions = [
        action
        for action in build_distribution_actions(registry, load_targets(DEFAULT_TARGETS), ROOT)
        if action.skill_name == "to-spec"
    ]

    assert matt_actions == []


def test_snapshot_output_path_uses_registry_snapshot_root(tmp_path: Path) -> None:
    registry = load_registry(ROOT / "agent-skills/registry/sources.jsonc")

    path = snapshot_output_path(registry, tmp_path, "before move", "2026-07-10T120000Z")

    assert path == tmp_path / ".agent-state/skill-snapshots/2026-07-10T120000Z-before-move.json"


def test_distribute_apply_rejects_devspace_worktree_by_default():
    with pytest.raises(RegistryError, match="DevSpace worktree"):
        _assert_safe_apply_root(Path.home() / ".devspace" / "worktrees" / "template-example")


def test_distribute_apply_allows_real_checkout_paths(tmp_path: Path):
    _assert_safe_apply_root(tmp_path / "real-checkout")


def test_distribute_filters_actions_by_surface_and_skill(capsys):
    result = main(
        [
            "distribute",
            "--dry-run",
            "--surface",
            "global",
            "--skill",
            "knowledge-lifecycle-manager",
        ]
    )

    assert result == 0
    assert "DRY-RUN distribution actions: 7" in capsys.readouterr().out

    result = main(
        [
            "distribute",
            "--dry-run",
            "--surface",
            "project",
            "--skill",
            "knowledge-lifecycle-manager",
        ]
    )

    assert result == 0
    assert "DRY-RUN distribution actions: 0" in capsys.readouterr().out

    result = main(
        [
            "distribute",
            "--dry-run",
            "--surface",
            "global",
            "--agent",
            "reasonix",
            "--skill",
            "knowledge-lifecycle-manager",
        ]
    )

    assert result == 0
    assert "DRY-RUN distribution actions: 1" in capsys.readouterr().out


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


def test_current_distribution_actions_are_directory_symlinks_only():
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

    actions = build_distribution_actions(registry, targets, ROOT)

    assert actions
    assert {action.action for action in actions} == {"link-dir"}


def test_bundle_distribution_resolves_catalog_relative_path(tmp_path: Path):
    import shutil

    source = tmp_path / "seed/to-spec"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: to-spec\ndescription: test fixture\n---\n",
        encoding="utf-8",
    )
    nested = tmp_path / "agent-skills/external/quarantine/mattpocock-skills/engineering/to-spec"
    nested.parent.mkdir(parents=True)
    shutil.copytree(source, nested)
    registry = load_registry(DEFAULT_REGISTRY)
    skill_key = ("mattpocock-skills", "to-spec")
    registry.skills[skill_key] = replace(
        registry.skills[skill_key],
        gate=replace(registry.skills[skill_key].gate, manual_approval=False, approved_hash=None),
    )

    actions = build_distribution_actions(registry, load_targets(DEFAULT_TARGETS), tmp_path)
    to_spec = [action for action in actions if action.skill_name == "to-spec" and action.target_agent == "codex"]

    assert to_spec
    assert to_spec[0].source == nested


def test_apply_distribution_actions_replaces_existing_directory_without_bak_residue(tmp_path: Path):
    source = tmp_path / "source/demo-skill"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\n", encoding="utf-8")

    target = tmp_path / "runtime-target/demo-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("---\nname: demo-skill\ndescription: old\n---\n", encoding="utf-8")

    action = DistributionAction(
        skill_name="demo-skill",
        source=source,
        target_agent="codex",
        target_path=target,
        action="link-dir",
    )
    apply_distribution_actions([action])

    assert target.is_symlink()
    assert target.resolve() == source.resolve()
    assert not (tmp_path / "runtime-target/demo-skill.bak").exists()
    assert list(tmp_path.glob("runtime-target/*.bak")) == []


def test_apply_distribution_actions_rejects_relative_target(tmp_path: Path):
    source = tmp_path / "source/demo-skill"
    source.mkdir(parents=True)
    action = DistributionAction(
        skill_name="demo-skill",
        source=source,
        target_agent="codex",
        target_path=Path("relative/demo-skill"),
        action="link-dir",
    )
    with pytest.raises(RegistryError, match="non-absolute target path"):
        apply_distribution_actions([action])


def test_apply_distribution_actions_rejects_home_target(tmp_path: Path):
    source = tmp_path / "source/demo-skill"
    source.mkdir(parents=True)
    action = DistributionAction(
        skill_name="demo-skill",
        source=source,
        target_agent="codex",
        target_path=Path.home(),
        action="link-dir",
    )
    with pytest.raises(RegistryError, match="unsafe root/home target path"):
        apply_distribution_actions([action])


def test_apply_distribution_actions_rejects_home_ancestor_target(tmp_path: Path):
    source = tmp_path / "source/demo-skill"
    source.mkdir(parents=True)
    for unsafe in (Path.home().parent, Path("/etc")):
        action = DistributionAction(
            skill_name="demo-skill",
            source=source,
            target_agent="codex",
            target_path=unsafe,
            action="link-dir",
        )
        with pytest.raises(RegistryError, match="unsafe root/home target path"):
            apply_distribution_actions([action])


def write_hygiene_registry(tmp_path: Path) -> Path:
    registry_path = tmp_path / "sources.jsonc"
    registry_path.write_text(
        f'''{{
          "version": 2,
          "paths": {{"local_root": "agent-skills/local", "quarantine_root": "agent-skills/external/quarantine", "lockfile": ".agent-state/skills-lock.json", "run_log_root": ".agent-state/skill-sync-runs", "snapshot_root": ".agent-state/skill-snapshots"}},
          "defaults": {{
            "external": {{"scope": "global", "agents": ["codex"], "audit": {{"required": true, "allow_unaudited": false, "allow_scripts": false}}, "gate": {{"manual_approval": true, "approved": false}}}},
            "internal": {{"scope": "project", "audit": {{"required": false}}, "gate": {{"approved": true}}}}
          }},
          "projects": {{"hygiene-demo": {{"skills_dir": "{tmp_path}/proj-skills"}}}},
          "sources": {{"external": {{"type": "external", "fetcher": "skills.sh", "ref": "owner/repo", "skills": {{"safe": {{}}}}}}}}
        }}''',
        encoding="utf-8",
    )
    return registry_path


def test_validate_runtime_hygiene_detects_bak_residue_and_divergent_realpaths(tmp_path: Path):
    agent_a = tmp_path / "agentA"
    agent_b = tmp_path / "agentB"
    (agent_a / "demo").mkdir(parents=True)
    (agent_a / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: a\n---\n", encoding="utf-8"
    )
    (agent_a / "stale.bak").mkdir()
    (agent_b / "other-real").mkdir(parents=True)
    (agent_b / "demo").symlink_to(agent_b / "other-real")

    targets = {
        "codex": SkillTarget(agent="codex", path=agent_a, format="directory", strategy="symlink"),
        "cross-agent": SkillTarget(agent="cross-agent", path=agent_b, format="directory", strategy="symlink"),
    }
    errors = validate_runtime_hygiene(load_registry(write_hygiene_registry(tmp_path)), targets, root=tmp_path)

    assert any("stale.bak" in err and "backup residue" in err for err in errors), errors
    divergent = [err for err in errors if "divergent realpaths" in err and "'demo'" in err]
    assert len(divergent) == 1, errors


def test_validate_runtime_hygiene_passes_when_realpaths_match(tmp_path: Path):
    agent_a = tmp_path / "agentA"
    agent_b = tmp_path / "agentB"
    canonical = tmp_path / "canonical" / "demo"
    canonical.mkdir(parents=True)
    (canonical / "SKILL.md").write_text("---\nname: demo\ndescription: c\n---\n", encoding="utf-8")
    agent_a.mkdir(parents=True)
    agent_b.mkdir(parents=True)
    (agent_a / "demo").symlink_to(canonical)
    (agent_b / "demo").symlink_to(canonical)

    targets = {
        "codex": SkillTarget(agent="codex", path=agent_a, format="directory", strategy="symlink"),
        "cross-agent": SkillTarget(agent="cross-agent", path=agent_b, format="directory", strategy="symlink"),
    }
    errors = validate_runtime_hygiene(load_registry(write_hygiene_registry(tmp_path)), targets, root=tmp_path)

    assert errors == []


def test_validate_runtime_hygiene_flags_residue_in_project_skills_dir(tmp_path: Path):
    proj_skills = tmp_path / "proj-skills"
    (proj_skills / "legacy.bak").mkdir(parents=True)

    errors = validate_runtime_hygiene(
        load_registry(write_hygiene_registry(tmp_path)),
        targets={},
        root=tmp_path,
    )

    assert any("legacy.bak" in err and "backup residue" in err for err in errors), errors


def test_project_internal_skill_distributes_to_agents_and_claude_project_views():
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

    actions = build_distribution_actions(registry, targets, ROOT)

    project_actions = [action for action in actions if action.skill_name == "ps-analytics"]
    assert len(project_actions) == 2
    assert all(action.target_agent is None for action in project_actions)
    assert {action.target_path.as_posix() for action in project_actions} == {
        f"{Path.home()}/work/projects/product_strategy/.agents/skills/ps-analytics",
        f"{Path.home()}/work/projects/product_strategy/.claude/skills/ps-analytics",
    }
    assert len({action.source for action in project_actions}) == 1


def test_project_external_shadow_skill_distributes_from_checked_in_shadow():
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

    actions = build_distribution_actions(registry, targets, ROOT)

    baoyu = [action for action in actions if action.skill_name == "baoyu-diagram"]
    assert len(baoyu) == 2
    assert all(action.target_agent is None for action in baoyu)
    assert {action.source for action in baoyu} == {
        ROOT / "agent-skills/local/shadows/baoyu/baoyu-diagram"
    }
    assert {action.target_path.as_posix() for action in baoyu} == {
        f"{Path.home()}/work/projects/product_strategy/.agents/skills/baoyu-diagram",
        f"{Path.home()}/work/projects/product_strategy/.claude/skills/baoyu-diagram",
    }


def test_project_views_link_to_the_same_canonical_skill_source(tmp_path: Path):
    registry = load_registry(DEFAULT_REGISTRY)
    registry = replace(
        registry,
        projects={
            **registry.projects,
            "product_strategy": {
                "skills_dir": str(tmp_path / ".agents/skills"),
                "compatibility_skills_dirs": {
                    "claude": str(tmp_path / ".claude/skills"),
                },
            },
        },
    )
    actions = [
        action
        for action in build_distribution_actions(
            registry,
            load_targets(DEFAULT_TARGETS),
            ROOT,
        )
        if action.skill_name == "ps-analytics"
    ]

    apply_distribution_actions(actions)

    assert len(actions) == 2
    assert all(action.target_path.is_symlink() for action in actions)
    assert {action.target_path.resolve() for action in actions} == {actions[0].source}


def test_reconcile_covers_project_compatibility_views(tmp_path: Path):
    registry = load_registry(DEFAULT_REGISTRY)
    product_skills = {
        key: skill
        for key, skill in registry.skills.items()
        if "product_strategy" in skill.projects
    }
    registry = replace(
        registry,
        projects={
            "product_strategy": {
                "skills_dir": str(tmp_path / ".agents/skills"),
                "compatibility_skills_dirs": {
                    "claude": str(tmp_path / ".claude/skills"),
                },
            }
        },
        skills=product_skills,
    )
    claude_root = tmp_path / ".claude/skills"
    claude_root.mkdir(parents=True)
    (claude_root / "stale-skill").symlink_to(
        ROOT / "agent-skills/local/product-strategy/ps-analytics"
    )

    actions = build_reconcile_actions(registry, {}, ROOT)

    assert any(
        action.target_name == "product_strategy:claude"
        and action.skill_name == "stale-skill"
        and action.action == "remove-symlink"
        for action in actions
    )


def test_reasonix_distribution_uses_directory_symlink():
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

    actions = build_distribution_actions(registry, targets, ROOT)

    reasonix = [
        action
        for action in actions
        if action.skill_name == "knowledge-lifecycle-manager" and action.target_agent == "reasonix"
    ][0]
    assert reasonix.action == "link-dir"
    assert reasonix.target_path.name == "knowledge-lifecycle-manager"


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
    assert not any(
        action.target_name == "codex" and action.skill_name == "knowledge-lifecycle-manager"
        for action in actions
    )

    filtered = filter_reconcile_actions(actions, surface="global", skill="stale-skill")
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


def test_reconcile_removes_managed_legacy_flat_md_after_target_migration(tmp_path: Path):
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)
    reasonix_root = tmp_path / "reasonix-skills"
    reasonix_root.mkdir()
    source = ROOT / "agent-skills/local/global/knowledge-lifecycle-manager/SKILL.md"
    (reasonix_root / "knowledge-lifecycle-manager.md").write_bytes(source.read_bytes())
    (reasonix_root / "user-note.md").write_text("keep", encoding="utf-8")
    targets = {
        **targets,
        "reasonix": type(targets["reasonix"])(
            agent="reasonix",
            path=reasonix_root,
            format="directory",
            strategy="symlink",
            legacy_formats=("flat-md",),
        ),
    }

    actions = build_reconcile_actions(registry, targets, ROOT)

    assert any(
        action.target_name == "reasonix"
        and action.skill_name == "knowledge-lifecycle-manager"
        and action.action == "remove-flat-md"
        for action in actions
    )
    assert not any(action.target_path.name == "user-note.md" for action in actions)

    filtered = filter_reconcile_actions(
        actions,
        surface="global",
        agent="reasonix",
        skill="knowledge-lifecycle-manager",
    )
    assert len(filtered) == 1
    assert filtered[0].target_name == "reasonix"


def test_reconcile_preserves_same_name_legacy_flat_md_without_source_match(tmp_path: Path):
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)
    reasonix_root = tmp_path / "reasonix-skills"
    reasonix_root.mkdir()
    (reasonix_root / "knowledge-lifecycle-manager.md").write_text("user copy", encoding="utf-8")
    targets = {
        **targets,
        "reasonix": type(targets["reasonix"])(
            agent="reasonix",
            path=reasonix_root,
            format="directory",
            strategy="symlink",
            legacy_formats=("flat-md",),
        ),
    }

    actions = build_reconcile_actions(registry, targets, ROOT)

    assert not any(action.target_path.name == "knowledge-lifecycle-manager.md" for action in actions)


def test_snapshot_captures_global_and_project_targets():
    registry = load_registry(DEFAULT_REGISTRY)
    targets = load_targets(DEFAULT_TARGETS)

    snapshot = build_distribution_snapshot(registry, targets, ROOT, label="test")

    assert snapshot["schema_version"] == 1
    assert "claude" in snapshot["global_targets"]
    assert "mac-bootstrap" in snapshot["project_targets"]
    assert "mac-bootstrap:claude" in snapshot["project_targets"]
    assert snapshot["global_targets"]["reasonix"]["format"] == "directory"
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
