from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest


DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

from summary_contracts import (  # noqa: E402
    EvidenceGroup,
    SummaryContractError,
    SummaryDocument,
    build_input_digest,
    canonical_json,
    load_contract_bundle,
    validate_summary_document,
)


def valid_item(*, item_type: str = "decision") -> dict:
    return {
        "item_type": item_type,
        "title": "统一入口",
        "conclusion": "所有周期总结通过 lifecycle manager。",
        "value": "消除双路径漂移。",
        "dimensions": ["计划组织", "专业知识"],
        "evidence_group_ids": ["evg_a"],
        "confidence": 0.95,
    }


def valid_daily_document() -> dict:
    return {
        "contract_version": "summary-v1",
        "taxonomy_version": "dimensions-v1",
        "policy_version": "summary-policy-v1",
        "level": "daily",
        "period": "2026-07-10",
        "headline": "完成结构化总结设计。",
        "items": [valid_item()],
    }


def test_daily_contract_accepts_item_level_dimensions():
    validated = validate_summary_document(valid_daily_document(), load_contract_bundle())

    assert validated["level"] == "daily"


@pytest.mark.parametrize(
    "dimensions",
    [
        ["计划组织", "专业知识", "创新"],
        ["未知"],
        ["计划组织", "计划组织"],
    ],
)
def test_contract_rejects_invalid_dimensions(dimensions: list[str]):
    doc = valid_daily_document()
    doc["items"][0]["dimensions"] = dimensions

    with pytest.raises(SummaryContractError, match="dimensions"):
        validate_summary_document(doc, load_contract_bundle())


@pytest.mark.parametrize("count", [1, 5])
def test_insight_count_is_zero_or_two_to_four(count: int):
    doc = valid_daily_document()
    doc["items"].extend(valid_item(item_type="insight") for _ in range(count))

    with pytest.raises(SummaryContractError, match="insight count"):
        validate_summary_document(doc, load_contract_bundle())


def test_contract_rejects_unknown_evidence_group():
    with pytest.raises(SummaryContractError, match="evidence_group_ids"):
        validate_summary_document(
            valid_daily_document(),
            load_contract_bundle(),
            evidence_group_ids={"evg_other"},
        )


def test_contract_rejects_placeholder_content():
    doc = valid_daily_document()
    doc["items"][0]["conclusion"] = "待归纳"

    with pytest.raises(SummaryContractError, match="placeholder"):
        validate_summary_document(doc, load_contract_bundle())


def test_weekly_and_higher_contracts_require_support_fields():
    bundle = load_contract_bundle()
    for level in ("weekly", "monthly", "quarterly", "yearly"):
        doc = valid_daily_document()
        doc["level"] = level
        doc["period"] = "2026-W28" if level == "weekly" else "2026-07"
        with pytest.raises(SummaryContractError, match="supporting_item_ids"):
            validate_summary_document(doc, bundle)

        doc["items"][0]["supporting_item_ids"] = ["item_a", "item_b"]
        doc["items"][0]["lower_summary_refs"] = ["70_Summaries/Daily/2026-07-10.md"]
        if level in {"monthly", "quarterly", "yearly"}:
            doc["items"][0]["period_change"] = "本周期形成稳定结构化入口。"
        assert validate_summary_document(doc, bundle)["level"] == level


def test_higher_contract_rejects_unresolved_or_mismatched_lower_refs():
    doc = valid_daily_document()
    doc["level"] = "weekly"
    doc["period"] = "2026-W28"
    doc["items"][0]["supporting_item_ids"] = ["item_a", "item_b"]
    doc["items"][0]["lower_summary_refs"] = ["70_Summaries/Daily/unrelated.md"]

    with pytest.raises(SummaryContractError, match="unknown lower summary refs"):
        validate_summary_document(
            doc,
            load_contract_bundle(),
            lower_item_ids={"item_a", "item_b"},
            lower_summary_refs={"70_Summaries/Daily/2026-07-10.md"},
            lower_item_refs={
                "item_a": "70_Summaries/Daily/2026-07-10.md",
                "item_b": "70_Summaries/Daily/2026-07-10.md",
            },
        )

    doc["items"][0]["lower_summary_refs"] = [
        "70_Summaries/Daily/2026-07-10.md",
        "70_Summaries/Daily/2026-07-11.md",
    ]
    with pytest.raises(SummaryContractError, match="supporting items do not match lower refs"):
        validate_summary_document(
            doc,
            load_contract_bundle(),
            lower_item_ids={"item_a", "item_b"},
            lower_summary_refs={
                "70_Summaries/Daily/2026-07-10.md",
                "70_Summaries/Daily/2026-07-11.md",
            },
            lower_item_refs={
                "item_a": "70_Summaries/Daily/2026-07-10.md",
                "item_b": "70_Summaries/Daily/2026-07-10.md",
            },
        )


def test_contract_versions_must_match_assets():
    doc = valid_daily_document()
    doc["taxonomy_version"] = "dimensions-v0"

    with pytest.raises(SummaryContractError, match="taxonomy_version"):
        validate_summary_document(doc, load_contract_bundle())


def test_contract_types_are_immutable_value_objects():
    group = EvidenceGroup(
        evidence_group_id="evg_a",
        evidence_kind="work",
        source_refs=("record:rec_a",),
        source_kinds=("record",),
        payload={"title": "evidence"},
    )
    document = SummaryDocument.from_dict(valid_daily_document())

    with pytest.raises(AttributeError):
        group.evidence_kind = "other"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        document.level = "weekly"  # type: ignore[misc]


def test_canonical_json_and_input_digest_are_order_stable():
    bundle = load_contract_bundle()
    evidence_a = {"groups": [{"id": "evg_a", "refs": ["a", "b"]}], "period": "2026-07-10"}
    evidence_b = {"period": "2026-07-10", "groups": [{"refs": ["a", "b"], "id": "evg_a"}]}

    assert canonical_json(evidence_a) == canonical_json(evidence_b)
    assert build_input_digest(
        level="daily",
        period="2026-07-10",
        evidence_packet=evidence_a,
        bundle=bundle,
        prompt="prompt text",
        backend_kind="openai",
        model="gpt-test",
    ) == build_input_digest(
        level="daily",
        period="2026-07-10",
        evidence_packet=evidence_b,
        bundle=bundle,
        prompt="prompt text",
        backend_kind="openai",
        model="gpt-test",
    )


def test_input_digest_changes_with_contract_or_prompt():
    bundle = load_contract_bundle()
    kwargs = {
        "level": "daily",
        "period": "2026-07-10",
        "evidence_packet": {"groups": []},
        "bundle": bundle,
        "prompt": "prompt-a",
        "backend_kind": "openai",
        "model": "gpt-test",
    }
    first = build_input_digest(**kwargs)

    changed = deepcopy(kwargs)
    changed["prompt"] = "prompt-b"
    assert build_input_digest(**changed) != first
