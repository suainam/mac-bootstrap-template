"""claim-first Skill: registry wiring, routing boundary, and asset integrity.

The Skill is the first-party merge of two upstream anti-defensive-writing
sources (kept as lineage, not as name). What must stay true is the routing
boundary (it must not restate `ste` or `humanizer-zh`), the fact guardrails,
and the reachability of every disclosed reference.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import TEMPLATE

ROOT = Path(TEMPLATE)
SKILL_DIR = ROOT / "agent-skills/local/global/claim-first"
SKILL_MD = SKILL_DIR / "SKILL.md"

sys.path.insert(0, str(ROOT))
from scripts.skill_registry import (  # noqa: E402
    load_registry,
    validate_skill_dir,
)

STEP_HEADINGS = [
    "### 1. 定主线",
    "### 2. 分类每句",
    "### 3. 删免责，写正向范围",
    "### 4. 校准不确定性",
    "### 5. 归位限定",
    "### 6. 交稿自查",
]


def read_skill() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_registered_as_enabled_global_internal_skill() -> None:
    registry = load_registry(ROOT / "agent-skills/registry/sources.jsonc")
    ref = registry.skills[("local-global", "claim-first")]
    assert ref.source_type == "internal"
    assert ref.scope == "global"
    assert ref.distribution_state == "enabled"
    # Same reach as the two writing skills it must not collide with.
    assert set(ref.agents) == {
        "claude",
        "codex",
        "opencode",
        "reasonix",
        "antigravity",
        "cross-agent",
    }


def test_supply_chain_validation_passes() -> None:
    assert validate_skill_dir(SKILL_DIR, "claim-first") == []


def test_description_routes_against_ste_and_humanizer_zh() -> None:
    """Losing this sentence makes the agent apply it to its own replies."""
    description = SKILL_MD.read_text(encoding="utf-8").split("---", 2)[1]
    assert "ste" in description
    assert "humanizer-zh" in description


def test_does_not_restate_ste_status_words() -> None:
    """`ste` owns the status vocabulary; a second copy drifts."""
    text = read_skill()
    for word in ("部分完成", "未验证", "阻塞", "未确认"):
        assert word not in text, f"status word restated from ste: {word}"


def test_does_not_restate_humanizer_pattern_catalog() -> None:
    """The 31-pattern catalog stays single-sourced in humanizer-zh."""
    text = read_skill()
    assert "粗体当装饰" not in text
    assert "客服腔" not in text
    assert "格言与伪深度" not in text


def test_fact_guardrails_present() -> None:
    text = read_skill()
    assert "不造事实" in text
    assert "相关不写成因果" in text
    assert "必要限定保留一次" in text
    assert "示例只给写法" in text
    assert "不造计划" in text
    assert "清过期标识符" in text


@pytest.mark.parametrize("heading", STEP_HEADINGS)
def test_every_step_states_a_completion_criterion(heading: str) -> None:
    text = read_skill()
    start = text.index(heading)
    following = text.find("\n### ", start + 1)
    section = text[start:] if following == -1 else text[start:following]
    assert "完成标准：" in section, f"step lacks completion criterion: {heading}"


def test_every_reference_pointer_resolves_to_a_file() -> None:
    text = read_skill()
    targets = [t for t in re.findall(r"\]\((references/[^)]+)\)", text)]
    assert targets, "skill discloses no reference files"
    for target in targets:
        assert (SKILL_DIR / target).is_file(), target


@pytest.mark.parametrize(
    ("reference", "required_rule"),
    [
        ("references/narrative.md", "缺实验时"),
        ("references/narrative.md", "不把不占优的指标设为主战场"),
        ("references/technical-sop.md", "保留清单"),
        ("references/technical-sop.md", "不可互相替代"),
        ("references/patterns.md", "保留边界"),
    ],
)
def test_reference_keeps_its_load_bearing_rule(reference: str, required_rule: str) -> None:
    body = (SKILL_DIR / reference).read_text(encoding="utf-8")
    assert required_rule in body


def test_paper_leading_phrase_has_exactly_one_home() -> None:
    """The branch selector carries it; a copy in the reference would drift."""
    assert "学术发布会" in read_skill()
    assert "学术发布会" not in (SKILL_DIR / "references/narrative.md").read_text(
        encoding="utf-8"
    )


CHECKER = SKILL_DIR / "scripts" / "check_rewrite.py"


def run_checker(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        capture_output=True,
        text=True,
        input=stdin,
    )


def test_golden_cases_satisfy_their_own_invariants() -> None:
    """Each case's expected rewrite passes, and its raw source fails."""
    result = run_checker("--self-test")
    assert result.returncode == 0, result.stderr


def test_checker_rejects_invented_quantity() -> None:
    """A fabricated sample size is the failure mode the guardrail names."""
    result = run_checker(
        "--case",
        "zh-metric-as-verdict",
        "--rewrite",
        "-",
        stdin="相同测试条件下，该方法把延迟从 100 ms 降到 60 ms，准确率为 89%，基线为 90%，并在五个数据集上验证。",
    )
    assert result.returncode == 1
    assert "invented figure" in result.stderr


def test_checker_rejects_dropped_quantity() -> None:
    result = run_checker(
        "--case",
        "zh-metric-as-verdict",
        "--rewrite",
        "-",
        stdin="该方法延迟更低。",
    )
    assert result.returncode == 1
    assert "dropped figure" in result.stderr


def test_checker_accepts_a_clean_rewrite() -> None:
    result = run_checker(
        "--case",
        "zh-metric-as-verdict",
        "--rewrite",
        "-",
        stdin="相同测试条件下，该方法把延迟从 100 ms 降到 60 ms，准确率为 89%，基线为 90%。",
    )
    assert result.returncode == 0, result.stderr


def test_checker_exits_two_on_unknown_case() -> None:
    """An unusable input is not a verdict on the rewrite."""
    result = run_checker("--case", "no-such-case", "--rewrite", "-", stdin="任意文本")
    assert result.returncode == 2


def test_examples_cases_are_reachable_from_the_skill() -> None:
    assert "examples/cases.json" in read_skill()
    assert (SKILL_DIR / "examples" / "cases.json").is_file()
