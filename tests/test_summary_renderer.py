from __future__ import annotations

from pathlib import Path
import sys


CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR.parent / "agent" / "data-hub"))

from summary_contracts import SummaryDocument
from summary_renderer import render_summary_markdown


def test_daily_renderer_separates_work_and_insights_with_item_tags():
    document = SummaryDocument.from_dict(
        {
            "contract_version": "summary-v1",
            "taxonomy_version": "dimensions-v1",
            "policy_version": "summary-policy-v1",
            "level": "daily",
            "period": "2026-07-10",
            "headline": "完成结构化摘要合同。",
            "items": [
                {"item_type": "outcome", "title": "合同", "conclusion": "已校验", "value": "防漂移", "dimensions": ["专业知识"], "evidence_group_ids": ["evg_a"], "confidence": 0.9},
                {"item_type": "insight", "title": "洞察", "conclusion": "证据先行", "value": "可复用", "dimensions": ["学习成长", "创新"], "evidence_group_ids": ["evg_b"], "confidence": 0.8},
            ],
        }
    )

    text = render_summary_markdown(document, revision_id="rev_test", input_digest="digest")

    assert "## 工作进展" in text
    assert "## 知识洞察" in text
    assert "#专业知识" in text
    assert "#学习成长 #创新" in text
    assert "evidence: evg_a" in text
    assert "revision_id: rev_test" in text
