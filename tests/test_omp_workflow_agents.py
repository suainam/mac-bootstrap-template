from pathlib import Path

import yaml

from helpers import TEMPLATE

AGENTS_DIR = Path(TEMPLATE) / "agent" / "omp" / "agents"


def _split_frontmatter(text: str):
    lines = text.splitlines()
    assert lines[0] == "---", "frontmatter must open with ---"
    end = lines.index("---", 1)
    return yaml.safe_load("\n".join(lines[1:end]))


def test_all_five_agents_present_and_self_consistent():
    expected = {
        "s-planner": "@plan",
        "s-designer": "@plan",
        "s-implementer": "@task",
        "s-reviewer": "@advisor",
        "s-retro": "@task",
        "s-skeptic": "@advisor",
        "s-acceptor": "@task",
    }
    files = {p.stem: p for p in AGENTS_DIR.glob("s-*.md")}
    assert set(files) == set(expected), f"expected dash {sorted(expected)}"

    for name, role in expected.items():
        data = _split_frontmatter(files[name].read_text())
        assert data.get("name") == name, f"{name}: frontmatter name mismatch"
        assert data.get("model") == role, f"{name}: model must be {role}"
        assert data.get("description"), f"{name}: missing description"
        assert data.get("tools"), f"{name}: missing tools"


def test_reviewer_has_no_mutating_tools():
    reviewer = _split_frontmatter((AGENTS_DIR / "s-reviewer.md").read_text())
    tools = {name.strip() for name in reviewer["tools"].split(",") if name.strip()}
    # `bash` stays: the reviewer needs read-only git/test invocations. It is
    # constrained by the prompt's read-only policy, not by the tool list.
    mutating = {"write", "edit", "task"}
    assert mutating.isdisjoint(tools), f"s-reviewer must not carry mutating tools: {sorted(tools & mutating)}"
    assert "bash" in tools, "s-reviewer needs bash for read-only git and test checks"


def _csv(value) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def test_only_writers_delegate_and_only_to_their_adversary():
    """Delegation must stay a closed graph: a missing spawns list defaults to '*'."""
    expected = {
        "s-planner": {"s-skeptic"},
        "s-designer": {"s-skeptic"},
        "s-implementer": {"s-acceptor"},
    }
    for path in AGENTS_DIR.glob("s-*.md"):
        data = _split_frontmatter(path.read_text())
        has_task = "task" in _csv(data["tools"])
        if path.stem in expected:
            assert has_task, f"{path.stem} must carry task"
            assert _csv(data.get("spawns")) == expected[path.stem], f"{path.stem} spawns must be {expected[path.stem]}"
        else:
            assert not has_task, f"{path.stem} must not carry task"
            assert not data.get("spawns"), f"{path.stem} must not declare spawns"


def test_subagent_delegation_contract_contains_mandated_reliability_rules():
    """Subagent Delegation Contract in AGENTS.md must enforce offline preflight,
    single-responsibility slicing, and progress heartbeats."""
    agents_rules_path = Path(TEMPLATE) / "agent" / "rules" / "AGENTS.md"
    assert agents_rules_path.is_file(), f"missing rules file: {agents_rules_path}"
    content = agents_rules_path.read_text(encoding="utf-8")

    assert "## Subagent Delegation Contract" in content
    assert "Offline preflight & no blind downloads" in content
    assert "Single responsibility & task slicing" in content
    assert "Progress heartbeat & deadlock prevention" in content
