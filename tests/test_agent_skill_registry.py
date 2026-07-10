"""Agent skill source registry authority checks."""

from __future__ import annotations

import json
import os
from pathlib import Path

from helpers import TEMPLATE


RETIRED_SKILL_GOVERNANCE_FILES = [
    "agent/skills-manifest.json",
    "agent/skills-distribution.json",
    "agent/skills-promote.txt",
    "scripts/skill_scope_manifest.py",
    "scripts/check-skill-scope.py",
    "scripts/skill-route.sh",
    "scripts/skill-scope-refresh.sh",
    "scripts/sync-agent-upstreams.sh",
]


def load_sources() -> dict:
    # This registry is JSONC, but the committed file currently avoids comments so
    # that this authority test can stay dependency-free.
    return json.loads(
        Path(TEMPLATE, "agent-skills", "registry", "sources.jsonc").read_text(
            encoding="utf-8"
        )
    )


def test_skill_sources_registry_is_authoritative():
    assert Path(TEMPLATE, "agent-skills/registry/sources.jsonc").is_file()
    assert Path(TEMPLATE, "agent-skills/registry/targets.jsonc").is_file()
    assert Path(TEMPLATE, "scripts/skill_supply_chain.py").is_file()
    assert not Path(TEMPLATE, "agent/skills-sources.jsonc").exists()
    assert not Path(TEMPLATE, "agent/skill-targets.jsonc").exists()
    assert not Path(TEMPLATE, "agent/skills").exists()


def test_previous_skill_governance_files_are_removed():
    for rel in RETIRED_SKILL_GOVERNANCE_FILES:
        assert not os.path.exists(os.path.join(TEMPLATE, rel)), rel


def test_product_strategy_project_skills_are_registered():
    registry = load_sources()
    sources = registry["sources"]
    assert sources["local-product-strategy"]["skills"]["python-data-analysis"]["projects"] == [
        "product_strategy"
    ]
    assert sources["local-product-strategy"]["skills"]["web-video-presentation-delivery"]["projects"] == [
        "product_strategy"
    ]
    assert sources["baoyu-skills"]["skills"]["baoyu-diagram"]["projects"] == [
        "product_strategy"
    ]
    assert sources["guizang-ppt-skill"]["skills"]["guizang-ppt-skill"]["projects"] == [
        "product_strategy"
    ]


def test_lifecycle_manager_is_global_but_stage_skills_are_project_scoped():
    registry = load_sources()
    sources = registry["sources"]
    manager = sources["local-global"]["skills"]["knowledge-lifecycle-manager"]
    skills = sources["local-mac-bootstrap"]["skills"]

    assert manager["scope"] == "global"
    for skill in [
        "knowledge-source-ingestion",
        "knowledge-claim-extraction",
        "knowledge-candidate-review",
        "knowledge-materialization",
        "knowledge-daily-weekly-synthesis",
        "knowledge-hygiene-audit",
        "knowledge-record",
        "knowledge-reuse-retrieval",
    ]:
        assert skills[skill]["scope"] == "project"
        assert skills[skill]["projects"] == ["mac-bootstrap"]
        assert skills[skill].get("distribution_state", "enabled") == "enabled"


def test_langgpt_prompt_writer_skill_registered_as_external_shadow():
    skill = "langgpt-prompt-writer"
    assert os.path.exists(
        os.path.join(
            TEMPLATE,
            "agent-skills",
            "local",
            "shadows",
            "langgpt",
            skill,
            "SKILL.md",
        )
    )
    registry = load_sources()
    langgpt = registry["sources"]["langgpt"]["skills"][skill]
    assert langgpt["agents"] == ["claude", "codex", "opencode", "cross-agent"]
    assert langgpt.get("distribution_state", "enabled") == "enabled"
    assert (
        langgpt["local_shadow_path"]
        == "agent-skills/local/shadows/langgpt/langgpt-prompt-writer"
    )
    assert skill not in registry["sources"]["local-global"]["skills"]


def test_data_hub_readme_mentions_knowledge_record_for_live_push():
    readme_path = os.path.join(TEMPLATE, "agent", "data-hub", "README.md")
    readme_text = open(readme_path, encoding="utf-8").read()

    assert "knowledge-record" in readme_text
    assert "knowledge-lifecycle-manager record" in readme_text
    assert "live record contract" in readme_text
