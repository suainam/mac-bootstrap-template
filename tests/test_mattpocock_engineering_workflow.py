"""Matt Pocock engineering workflow registry contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.skill_supply_chain import DEFAULT_REGISTRY, load_registry  # noqa: E402


ALL_AGENTS = ("claude", "codex", "opencode", "reasonix", "antigravity", "cross-agent")
DIRECTORY_AGENTS = tuple(agent for agent in ALL_AGENTS if agent != "reasonix")


@pytest.fixture(scope="module")
def registry():
    return load_registry(DEFAULT_REGISTRY)


@pytest.mark.parametrize(
    ("name", "content_hash", "agents"),
    [
        (
            "setup-matt-pocock-skills",
            "sha256:d1d1b40f71fcb294d27a1b00297d1d25bcff3bc1e8759794a4af906b243d8e31",
            ALL_AGENTS,
        ),
        (
            "tdd",
            "sha256:aaed5857190bc8088332725c9c8deecf560744f6f7ef0bdfccf4bdf3fe678c16",
            ALL_AGENTS,
        ),
        (
            "to-spec",
            "sha256:f525dab8b9bd3961aa4813d8568ef6184f6e24aad5a020e129165ca6c220f836",
            ALL_AGENTS,
        ),
        (
            "to-tickets",
            "sha256:6eccfac132d92b949821d154679adc7f597bfc3e8c929f3c03786b92f91b961f",
            ALL_AGENTS,
        ),
        (
            "wayfinder",
            "sha256:62a0ab7262d40119da048328a71aeadaeaa21a4049ee9268d14500921bb6e257",
            ALL_AGENTS,
        ),
        (
            "implement",
            "sha256:72f446ef5b35d3df73c21b574ba2ae50ab3d02fc5d4da44b80f27ce13e7dc18d",
            DIRECTORY_AGENTS,
        ),
        (
            "code-review",
            "sha256:cd5bdf2afe1680d10150ae58abacbc32e7a11d034be76c7ef6fad58546ce85e3",
            DIRECTORY_AGENTS,
        ),
    ],
)
def test_workflow_skill_is_enabled_and_hash_bound(
    name: str,
    content_hash: str,
    agents: tuple[str, ...],
    registry,
):
    skill = registry.skills[("mattpocock-skills", name)]

    assert skill.distribution_state == "enabled"
    assert skill.scope == "global"
    assert skill.agents == agents
    assert skill.gate.approved is True
    assert skill.gate.approved_hash == content_hash
    assert skill.audit.allow_unaudited is True
    assert skill.audit.allow_scripts is False


@pytest.mark.parametrize(
    ("source_id", "name"),
    [
        ("everything-claude-code", "tdd-workflow"),
        ("superpowers", "test-driven-development"),
    ],
)
def test_tdd_alternatives_remain_merged(source_id: str, name: str, registry):
    skill = registry.skills[(source_id, name)]

    assert skill.distribution_state == "merged"
