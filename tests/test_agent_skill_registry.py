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
    promote = open(os.path.join(TEMPLATE, "agent", "skills-promote.txt")).read()
    assert skill in promote
    assert os.path.exists(
        os.path.join(TEMPLATE, "agent", "skills", "personal", skill, "SKILL.md")
    )

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
    promote = open(os.path.join(TEMPLATE, "agent", "skills-promote.txt")).read()
    assert skill in promote
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
