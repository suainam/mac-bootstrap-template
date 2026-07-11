"""Matt Pocock engineering workflow registry contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.skill_supply_chain import DEFAULT_REGISTRY, load_registry  # noqa: E402


ALL_AGENTS = ("claude", "codex", "opencode", "pi", "reasonix", "antigravity", "cross-agent")
DIRECTORY_AGENTS = tuple(agent for agent in ALL_AGENTS if agent != "reasonix")


@pytest.fixture(scope="module")
def registry():
    return load_registry(DEFAULT_REGISTRY)


@pytest.mark.parametrize(
    ("name", "content_hash", "agents"),
    [
        (
            "setup-matt-pocock-skills",
            "sha256:41a52a12eaeb5302c9a672af40d4090988b43758438855f0927dc378a2ddd570",
            ALL_AGENTS,
        ),
        (
            "tdd",
            "sha256:e8ecf2e6373d026ec1926fcfb4bf61510e614754c6a9402cd8f33105f5c0d258",
            ALL_AGENTS,
        ),
        (
            "to-spec",
            "sha256:305911f9a65016bf31b209ade13da492042e3ebe1434db4161a777a4efc69dbb",
            ALL_AGENTS,
        ),
        (
            "to-tickets",
            "sha256:d03c2c1e5fee2080647ca49e6e4849cf5bbaf9250af9862ebc629d66f181b140",
            ALL_AGENTS,
        ),
        (
            "implement",
            "sha256:37152c34127f0609d05e7de3859e8273cefbdadebcb008bf7d46b95e325ce383",
            DIRECTORY_AGENTS,
        ),
        (
            "code-review",
            "sha256:a0a6ea333e7fd617515f47613832e1f2decb3abf18ac313d7fd0ea5ddda04365",
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
