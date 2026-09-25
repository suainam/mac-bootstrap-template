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
            "sha256:570d12b3caf6c468d77e0aba8602efc7a5346697a77cb5372f623cf67247784b",
            ALL_AGENTS,
        ),
        (
            "tdd",
            "sha256:2da488cb71308948f58928bbbae6d55d060d5414d5bb3ec7ee7d4bb73c670442",
            ALL_AGENTS,
        ),
        (
            "to-spec",
            "sha256:f525dab8b9bd3961aa4813d8568ef6184f6e24aad5a020e129165ca6c220f836",
            ALL_AGENTS,
        ),
        (
            "to-tickets",
            "sha256:5c1691ddf02291d5189213f8ffc82d2b05451131929bbc9e99052f912a05c300",
            ALL_AGENTS,
        ),
        (
            "wayfinder",
            "sha256:fa164901a041cab31d281288ea4b5af5aeb0a0d557b586cf6b341998a3fb3eb3",
            ALL_AGENTS,
        ),
        (
            "implement",
            "sha256:1a7a56bca542f46ff8e42fa5ddd293dab21b38b6dad57e1bf3e76d12e41c5fc2",
            DIRECTORY_AGENTS,
        ),
        (
            "code-review",
            "sha256:2bf54bc5e5eed6f8c78b2dbe99bfcfcc0e0221e0c11dbf07ff0f27effb2aed76",
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
