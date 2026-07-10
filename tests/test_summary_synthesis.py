from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR.parent / "agent" / "data-hub"))

from summary_contracts import load_contract_bundle
from summary_synthesis import prompt_name_for, synthesize_summary


def valid_daily_document():
    detailed = "结构化证据已校验并可复用。" * 16
    return {
        "contract_version": "summary-v1",
        "taxonomy_version": "dimensions-v1",
        "policy_version": "summary-policy-v1",
        "level": "daily",
        "period": "2026-07-10",
        "headline": detailed,
        "items": [
            {
                "item_type": "outcome",
                "title": detailed,
                "conclusion": detailed,
                "value": detailed,
                "dimensions": ["专业知识"],
                "evidence_group_ids": ["evg_abc"],
                "confidence": 0.9,
            }
        ],
    }


class FakeBackend:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate(self, prompt):
        self.calls.append(prompt)
        return self.outputs.pop(0)


@pytest.mark.parametrize(
    ("level", "prompt_name"),
    [
        ("daily", "daily-summary.md"),
        ("weekly", "weekly-summary.md"),
        ("monthly", "higher-period-summary.md"),
        ("quarterly", "higher-period-summary.md"),
        ("yearly", "higher-period-summary.md"),
    ],
)
def test_level_selects_contract_prompt(level, prompt_name):
    assert prompt_name_for(level) == prompt_name


def test_invalid_json_retries_once_with_validation_error():
    backend = FakeBackend(["not-json", json.dumps(valid_daily_document())])
    result = synthesize_summary(
        level="daily",
        period_id="2026-07-10",
        evidence={"evidence_groups": [{"evidence_group_id": "evg_abc", "evidence_kind": "local", "source_refs": ["10_Periodic/Daily/2026-07-10.md"], "source_kinds": ["daily_note"], "payload": {"snippet": "Verified work evidence."}}]},
        bundle=load_contract_bundle(),
        backend=backend,
    )

    assert result.level == "daily"
    assert len(backend.calls) == 2
    assert "previous response failed validation" in backend.calls[1]
