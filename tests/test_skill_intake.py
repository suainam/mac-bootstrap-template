"""Skill bundle discovery, external fetch, gate, and promotion checks."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.skill_supply_chain import (  # noqa: E402
    DEFAULT_REGISTRY,
    DEFAULT_TARGETS,
    BundleCatalogEntry,
    build_health_report,
    discover_bundle_catalog,
    ensure_external_bundles,
    ensure_external_skills,
    evaluate_gate,
    fetch_candidate_destination,
    fetch_external_bundle,
    fetch_external_skill,
    inspect_skill_content,
    load_registry,
    load_targets,
    main,
    promote_external_bundle,
    promote_external_skill,

    write_run_log,
)


def test_enabled_bundle_is_not_refetched_when_catalog_and_sources_are_present(tmp_path: Path) -> None:
    registry = load_registry(DEFAULT_REGISTRY)
    for bundle in registry.bundles.values():
        catalog_path = tmp_path / bundle.catalog_path
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        skills = []
        for skill in registry.skills.values():
            if skill.bundle_id != bundle.source_id or skill.distribution_state != "enabled":
                continue
            relative_path = Path(skill.name)
            source = tmp_path / bundle.quarantine_path / relative_path
            source.mkdir(parents=True, exist_ok=True)
            skills.append(
                {
                    "name": skill.name,
                    "relative_path": relative_path.as_posix(),
                    "content_hash": "sha256:" + "0" * 64,
                }
            )
        catalog_path.write_text(
            json.dumps({"source_id": bundle.source_id, "ref": bundle.ref, "skills": skills}),
            encoding="utf-8",
        )

    assert ensure_external_bundles(registry, tmp_path) == ()


def test_discover_bundle_catalog_hashes_each_skill_tree(tmp_path: Path) -> None:
    bundle_root = tmp_path / "agent-skills/external/quarantine/mattpocock-skills"
    first = bundle_root / "engineering" / "alpha"
    second = bundle_root / "productivity" / "beta"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "SKILL.md").write_text("# alpha\n", encoding="utf-8")
    (second / "SKILL.md").write_text("# beta\n", encoding="utf-8")
    registry = load_registry(ROOT / "agent-skills/registry/sources.jsonc")

    entries = discover_bundle_catalog(registry.bundles["mattpocock-skills"], tmp_path)

    assert entries == (
        BundleCatalogEntry(
            name="alpha",
            relative_path=Path("engineering/alpha"),
            content_hash=inspect_skill_content(first).content_hash,
        ),
        BundleCatalogEntry(
            name="beta",
            relative_path=Path("productivity/beta"),
            content_hash=inspect_skill_content(second).content_hash,
        ),
    )




def test_fetch_external_skill_uses_registry_candidate_root(tmp_path: Path) -> None:
    registry_path = write_registry_for_external(tmp_path, "safe")
    raw = registry_path.read_text(encoding="utf-8").replace(
        '"quarantine_root": "agent-skills/external/quarantine"',
        '"quarantine_root": "custom/quarantine"',
    )
    registry_path.write_text(raw, encoding="utf-8")
    registry = load_registry(registry_path)
    skill = registry.skills[("external", "safe")]

    result = fetch_external_skill(skill, registry, tmp_path, dry_run=True)

    assert result.cwd == tmp_path / "custom/quarantine/.tmp/external/safe/work"
    assert result.destination == tmp_path / ".agent-state/skill-candidates/external/safe"


def test_fetch_external_bundle_uses_bundle_quarantine_root(tmp_path: Path) -> None:
    registry = load_registry(DEFAULT_REGISTRY)
    bundle = registry.bundles["mattpocock-skills"]

    result = fetch_external_bundle(bundle, tmp_path, dry_run=True)

    assert result.cwd == tmp_path / "agent-skills/external/quarantine/.tmp/mattpocock-skills/bundle/work"
    assert result.destination == tmp_path / ".agent-state/skill-candidates/mattpocock-skills"


def test_per_skill_fetch_rejects_bundle_managed_source(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["fetch", "--source", "mattpocock-skills", "--skill", "to-spec", "--dry-run"]) == 1
    assert "use fetch-bundle --source mattpocock-skills" in capsys.readouterr().err


def test_fetch_external_bundle_catalogs_staged_content_without_runtime_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = load_registry(DEFAULT_REGISTRY)
    bundle = registry.bundles["mattpocock-skills"]

    def fake_run(command, cwd, env, text, capture_output, check, **kwargs):
        skill = Path(cwd) / ".agents/skills/alpha"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# alpha\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="fetched", stderr="")

    monkeypatch.setattr("scripts.skill_supply_chain.subprocess.run", fake_run)
    result = fetch_external_bundle(bundle, tmp_path)

    assert result.returncode == 0
    assert (result.destination / "alpha/SKILL.md").is_file()
    catalog = json.loads((result.destination / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["skills"][0]["name"] == "alpha"
    assert not (tmp_path / "agent-skills/external/quarantine/mattpocock-skills").exists()
    assert not (tmp_path / ".claude/skills").exists()


def test_promote_external_bundle_updates_existing_script_free_skill(tmp_path: Path) -> None:
    registry = load_registry(DEFAULT_REGISTRY)
    bundle = registry.bundles["mattpocock-skills"]
    skill = registry.skills[("mattpocock-skills", "to-spec")]
    skill = replace(
        skill,
        gate=replace(skill.gate, approved_hash="sha256:" + "0" * 64, auto_update=True),
        audit=replace(skill.audit, allow_unaudited=True, max_risk="LOW"),
    )
    registry = replace(registry, skills={**registry.skills, (skill.source_id, skill.name): skill})

    active = tmp_path / bundle.quarantine_path / "to-spec"
    active.mkdir(parents=True)
    (active / "SKILL.md").write_text("# old\n", encoding="utf-8")
    candidate = tmp_path / registry.paths["candidate_root"] / bundle.source_id / "to-spec"
    candidate.mkdir(parents=True)
    (candidate / "SKILL.md").write_text("# updated\n", encoding="utf-8")
    entry = BundleCatalogEntry(
        name="to-spec",
        relative_path=Path("to-spec"),
        content_hash=inspect_skill_content(candidate).content_hash,
    )
    from scripts.skill_supply_chain import write_bundle_catalog

    write_bundle_catalog(bundle, (entry,), tmp_path, output_path=candidate.parent / "catalog.json")

    result = promote_external_bundle(registry, bundle, tmp_path)

    assert result.promoted == ("to-spec",)
    assert result.blocked == ()
    assert (tmp_path / bundle.quarantine_path / "to-spec/SKILL.md").read_text(encoding="utf-8") == "# updated\n"
    assert (tmp_path / bundle.catalog_path).is_file()


def test_write_run_log_uses_registry_run_log_root(tmp_path: Path) -> None:
    registry_path = write_registry_for_external(tmp_path, "safe")
    raw = registry_path.read_text(encoding="utf-8").replace(
        '"run_log_root": ".agent-state/skill-sync-runs"',
        '"run_log_root": "custom/run-logs"',
    )
    registry_path.write_text(raw, encoding="utf-8")
    registry = load_registry(registry_path)

    path = write_run_log({"event": "test"}, registry, tmp_path)

    assert path.parent == tmp_path / "custom/run-logs"
    assert json.loads(path.read_text(encoding="utf-8"))["event"] == "test"




def test_mattpocock_commands_include_skills_sh_page_backed_skills():
    registry = load_registry(DEFAULT_REGISTRY)

    assert registry.skills[("mattpocock-skills", "diagnose")].distribution_state == "disabled"
    expected_agents = (
        "claude",
        "codex",
        "opencode",
        "reasonix",
        "antigravity",
        "cross-agent",
    )
    expected_hashes = {
        "codebase-design": "sha256:61f4936a45f334e894fe4c7e9b1bbaf509c1b451c2f8bddf91e563ac6ae82422",
        "diagnosing-bugs": "sha256:29faf0d352422aa58beb0ce4666a49bdfdd5d2cc065c9dfe9be7b7e89fbdf584",
        "domain-modeling": "sha256:18a9314d338b8135e4108d1d31d2fd57ad289cf8bf31d2acd6a6f3053ac22a38",
        "grilling": "sha256:27f71f106a7062691b2982d4f847304a62930ebed8b50734f4d4fd498d60afa8",
    }
    for name, expected_hash in expected_hashes.items():
        skill = registry.skills[("mattpocock-skills", name)]
        assert skill.distribution_state == "enabled"
        assert skill.scope == "global"
        assert skill.agents == expected_agents
        assert skill.gate.approved is True
        assert skill.gate.approved_hash == expected_hash

    diagnosing_bugs = registry.skills[("mattpocock-skills", "diagnosing-bugs")]
    assert diagnosing_bugs.audit.allow_unaudited is True
    assert diagnosing_bugs.audit.allow_scripts is True

    handoff = registry.skills[("mattpocock-skills", "handoff")]
    assert handoff.scope == "global"
    assert handoff.distribution_state == "enabled"
    assert handoff.agents == (
        "claude",
        "codex",
        "opencode",
        "reasonix",
        "antigravity",
        "cross-agent",
    )

    assert registry.skills[("mattpocock-skills", "write-a-skill")].distribution_state == "staged"
    assert registry.skills[("mattpocock-skills", "zoom-out")].distribution_state == "staged"




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


def test_promote_external_skill_forwards_staged_candidate_into_quarantine(tmp_path: Path) -> None:
    registry = load_registry(write_registry_for_external(tmp_path, "safe"))
    skill = registry.skills[("external", "safe")]
    candidate = fetch_candidate_destination(registry, skill, tmp_path)
    candidate.mkdir(parents=True)
    (candidate / "SKILL.md").write_text(
        "---\nname: safe\ndescription: Safe\n---\n\n# Safe\n",
        encoding="utf-8",
    )
    current_hash = inspect_skill_content(candidate).content_hash
    skill = replace(
        skill,
        gate=replace(skill.gate, approved=True, approved_hash=current_hash),
        audit=replace(skill.audit, allow_unaudited=True),
    )
    registry = replace(registry, skills={**registry.skills, ("external", "safe"): skill})

    result = promote_external_skill(registry, skill, tmp_path)

    assert result.promoted == ("safe",)
    assert result.blocked == ()
    assert (tmp_path / skill.quarantine_path / "SKILL.md").is_file()


def test_promote_external_skill_blocks_mismatched_approval(tmp_path: Path) -> None:
    registry = load_registry(write_registry_for_external(tmp_path, "safe", approved_hash="old"))
    skill = registry.skills[("external", "safe")]
    candidate = fetch_candidate_destination(registry, skill, tmp_path)
    candidate.mkdir(parents=True)
    (candidate / "SKILL.md").write_text(
        "---\nname: safe\ndescription: Safe\n---\n\n# Safe\n",
        encoding="utf-8",
    )
    skill = replace(skill, audit=replace(skill.audit, allow_unaudited=True))
    registry = replace(registry, skills={**registry.skills, ("external", "safe"): skill})
    result = promote_external_skill(registry, skill, tmp_path)

    assert result.promoted == ()

    assert "approved hash does not match current content" in result.blocked[0]
    assert not (tmp_path / skill.quarantine_path).exists()


def test_build_health_report_flags_missing_and_drifted_enabled_sources(tmp_path: Path) -> None:
    registry_path = write_registry_for_external(tmp_path, "safe", approved_hash="old")
    registry = load_registry(registry_path)
    skill = registry.skills[("external", "safe")]
    candidate = fetch_candidate_destination(registry, skill, tmp_path)
    candidate.mkdir(parents=True)
    (candidate / "SKILL.md").write_text(
        "---\nname: safe\ndescription: Safe\n---\n\n# Safe\n",
        encoding="utf-8",
    )
    skill = replace(skill, audit=replace(skill.audit, allow_unaudited=True))
    registry = replace(registry, skills={**registry.skills, ("external", "safe"): skill})
    # stage candidate only; quarantine absent -> source missing
    report = build_health_report(registry, tmp_path)
    row = report["skills"][0]
    assert row["source_present"] is False

    # promote with a matching approval, then mutate quarantine to create drift
    current_hash = inspect_skill_content(candidate).content_hash
    skill = replace(
        skill,
        gate=replace(skill.gate, approved=True, approved_hash=current_hash),
        audit=replace(skill.audit, allow_unaudited=True),
    )
    registry = replace(registry, skills={**registry.skills, ("external", "safe"): skill})
    promote_external_skill(registry, skill, tmp_path)
    row = build_health_report(registry, tmp_path)["skills"][0]
    assert row["source_present"] is True
    assert row["drift"] is False

    (tmp_path / skill.quarantine_path / "SKILL.md").write_text(
        "---\nname: safe\ndescription: Safe\n---\n\n# Safe edited\n",
        encoding="utf-8",
    )
    row = build_health_report(registry, tmp_path)["skills"][0]
    assert row["source_present"] is True
    assert row["drift"] is True
