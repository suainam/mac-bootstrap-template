"""Agent skill promotion and distribution registry checks."""

import json
import os

from helpers import TEMPLATE


def test_obsidian_skills_promoted():
    content = open(os.path.join(TEMPLATE, "agent", "skills-promote.txt")).read()
    assert "# ── obsidian-skills" in content
    for skill in [
        "obsidian-markdown",
        "obsidian-bases",
        "json-canvas",
        "obsidian-cli",
        "defuddle",
    ]:
        assert skill in content


def test_langgpt_prompt_writer_skill_registered():
    skill = "langgpt-prompt-writer"
    assert os.path.exists(
        os.path.join(TEMPLATE, "agent", "skills", "personal", skill, "SKILL.md")
    )

    with open(os.path.join(TEMPLATE, "agent", "skills-manifest.json")) as fh:
        manifest = json.load(fh)
    assert skill in manifest["global_skills"]

    with open(os.path.join(TEMPLATE, "agent", "skills-distribution.json")) as fh:
        distribution = json.load(fh)
    assert distribution["skills"][skill]["apps"] == [
        "claude",
        "codex",
        "opencode",
        "cross-agent",
    ]


def test_decrypt_materialize_skill_registered_for_product_strategy_scope():
    skill = "decrypt-materialize"
    assert os.path.exists(
        os.path.join(TEMPLATE, "agent", "skills", "personal", skill, "SKILL.md")
    )

    with open(os.path.join(TEMPLATE, "agent", "skills-manifest.json")) as fh:
        manifest = json.load(fh)
    assert skill in manifest["projects"]["product_strategy"]["skills"]
    assert (
        manifest["projects"]["product_strategy"]["skills_dir"]
        == "${HOME}/work/projects/product_strategy/.agents/skills"
    )


def test_sync_agent_upstreams_reads_global_skills_from_manifest():
    content = open(
        os.path.join(TEMPLATE, "scripts", "sync-agent-upstreams.sh")
    ).read()
    assert "global-skills" in content
    assert "skill_scope_manifest.py" in content


def test_global_skills_match_personal_dir():
    with open(os.path.join(TEMPLATE, "agent", "skills-manifest.json")) as fh:
        manifest = json.load(fh)

    personal_dir = os.path.join(TEMPLATE, "agent", "skills", "personal")
    on_disk = {d for d in os.listdir(personal_dir) if os.path.isdir(os.path.join(personal_dir, d))}

    for skill in manifest["global_skills"]:
        assert skill in on_disk, (
            f"global_skills has '{skill}' but no SKILL.md at agent/skills/personal/{skill}/"
        )
        assert os.path.exists(
            os.path.join(personal_dir, skill, "SKILL.md")
        ), f"Missing SKILL.md for global skill: {skill}"


def test_knowledge_record_is_merged_into_lifecycle_manager():
    with open(os.path.join(TEMPLATE, "agent", "skills-manifest.json")) as fh:
        manifest = json.load(fh)
    assert "knowledge-record" not in manifest["global_skills"]
    assert "knowledge-lifecycle-manager" in manifest["projects"]["mac-bootstrap"]["skills"]

    with open(os.path.join(TEMPLATE, "agent", "skills-distribution.json")) as fh:
        distribution = json.load(fh)
    assert "knowledge-record" not in distribution["skills"]

    lifecycle_skill = os.path.join(
        TEMPLATE, "agent", "skills", "personal", "knowledge-lifecycle-manager", "SKILL.md"
    )
    lifecycle_text = open(lifecycle_skill).read()
    assert "record knowledge" in lifecycle_text
    assert "knowledge_records" in lifecycle_text
