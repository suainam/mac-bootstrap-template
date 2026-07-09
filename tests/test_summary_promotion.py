from __future__ import annotations

import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent / "agent" / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from promote_summary_knowledge import promote_summary_items


def test_promote_summary_items_writes_knowledge_note(tmp_path: Path):
    summary = tmp_path / "70_Summaries" / "Weekly" / "2026-W28.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        "---\nsummary_level: weekly\npromotion_status: not_reviewed\n---\n\n"
        "# Weekly Summary 2026-W28\n\n## Candidate: Keep API context narrow\n\n"
        "- reason: retrieval became easier\n",
        encoding="utf-8",
    )

    outputs = promote_summary_items(
        summary,
        selections=[
            {
                "title": "Keep API context narrow",
                "candidate_type": "card",
                "promotion_reason": "reused across summary cycles",
                "content": "Keep llm_wiki API context narrow and explicit.",
            }
        ],
    )

    assert outputs == ["40_Knowledge/Cards/2026-W28-keep-api-context-narrow.md"]
    note = (tmp_path / outputs[0]).read_text(encoding="utf-8")
    assert "promoted_from: 70_Summaries/Weekly/2026-W28.md" in note
    assert "promotion_reason: reused across summary cycles" in note
