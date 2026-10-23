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
