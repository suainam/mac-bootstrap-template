import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(SCRIPTS_DIR))

from candidate_review_io import parse_candidate_review, render_candidate_markdown, suggested_materialized_path


def test_render_candidate_markdown_keeps_machine_readable_fields():
    rows = [
        {
            "id": "cand_demo_daily",
            "candidate_type": "daily",
            "status": "pending",
            "title": "跟进门店实验",
            "content": "联系运营确认实验窗口。",
            "confidence": 0.91,
            "metadata_json": '{"source_type":"meeting_note","document_title":"门店实验周会"}',
            "materialized_path": None,
        },
        {
            "id": "cand_demo_adr",
            "candidate_type": "adr",
            "status": "accepted",
            "title": "采用 filename_first 归因",
            "content": "默认按文件名日期归因。",
            "confidence": 0.88,
            "metadata_json": '{"source_type":"wiki_page","document_title":"知识库方案"}',
            "materialized_path": "40_Knowledge/ADR/2026-07-04-filename-first.md",
        },
    ]

    rendered = render_candidate_markdown("2026-07-04", rows)

    assert "# Candidate Review 2026-07-04" in rendered
    assert "- candidate_id: `cand_demo_daily`" in rendered
    assert "- review_action: `pending`" in rendered
    assert "- review_action: `accept`" in rendered
    assert "40_Knowledge/ADR/2026-07-04-filename-first.md" in rendered


def test_parse_candidate_review_reads_updated_actions(tmp_path: Path):
    review_path = tmp_path / "2026-07-04.md"
    review_path.write_text(
        """
---
type: candidate-review
date: 2026-07-04
status: active
---

# Candidate Review 2026-07-04

## DAILY

### 跟进门店实验
- candidate_id: `cand_daily`
- status: `pending`
- review_action: `accept`
- confidence: `0.91`
- source: `meeting_note` / `门店实验周会`
- suggested_action: `daily`
- suggested_path: `10_Periodic/Daily/2026-07-04.md`
- review_note: 需要当天落日报

```text
联系运营确认实验窗口。
```
""".strip(),
        encoding="utf-8",
    )

    items = parse_candidate_review(review_path)

    assert len(items) == 1
    assert items[0].candidate_id == "cand_daily"
    assert items[0].review_action == "accept"
    assert items[0].review_note == "需要当天落日报"


def test_suggested_materialized_path_uses_slug_for_knowledge_notes():
    assert suggested_materialized_path("2026-07-04", "daily", "cand_demo", "跟进门店实验") == "10_Periodic/Daily/2026-07-04.md"
    assert suggested_materialized_path("2026-07-04", "adr", "cand_demo", "Use filename first") == "40_Knowledge/ADR/2026-07-04-use-filename-first.md"
