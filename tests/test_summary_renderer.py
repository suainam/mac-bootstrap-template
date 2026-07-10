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
    assert "`专业知识`" in text
    assert "`学习成长` `创新`" in text
    assert "**证据**：`evg_a`" in text
    assert "revision_id: rev_test" in text


def test_weekly_renderer_uses_review_sections_and_wikilinks():
    document = SummaryDocument.from_dict(
        {"contract_version":"summary-v1","taxonomy_version":"dimensions-v1","policy_version":"summary-policy-v1","level":"weekly","period":"2026-W28","headline":"复盘","items":[{"item_type":"decision","title":"取舍","conclusion":"以 evidence 为先","value":"降低漂移","dimensions":["计划组织"],"evidence_group_ids":["evg_a"],"confidence":0.9,"supporting_item_ids":["item_a","item_b"],"lower_summary_refs":["70_Summaries/Daily/2026-07-10.md"]}]}
    )
    text = render_summary_markdown(document, revision_id="rev_week", input_digest="digest")
    assert "## 决策与变化" in text
    assert "## Daily 索引" in text
    assert "[[70_Summaries/Daily/2026-07-10|2026-07-10]]" in text
