from __future__ import annotations

import sys
from pathlib import Path

DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

from db_helper import get_db_connection
from summary_contracts import EvidenceGroup, SummaryDocument
from summary_inputs import previous_level, resolve_lower_revisions
from summary_store import ensure_logical_summary, finalize_revision, full_file_sha256, mark_file_published, stage_revision


def _daily_document():
    return SummaryDocument.from_dict({"contract_version":"summary-v1","taxonomy_version":"dimensions-v1","policy_version":"summary-policy-v1","level":"daily","period":"2026-07-10","headline":"done","items":[{"item_type":"outcome","title":"done","conclusion":"done","value":"done","dimensions":["专业知识"],"evidence_group_ids":["evg_a"],"confidence":1.0}]})


def test_previous_level_mapping():
    assert previous_level("weekly") == "daily"


def test_resolve_lower_revisions_never_reads_markdown_body(tmp_path, monkeypatch):
    conn = get_db_connection(tmp_path / "db.sqlite")
    artifact = tmp_path / "daily.md"
    artifact.write_text("summary", encoding="utf-8")
    summary_id = ensure_logical_summary(conn, "daily", "2026-07-10")
    revision = stage_revision(conn, summary_id=summary_id, input_digest="digest", coverage_start="2026-07-10", coverage_end="2026-07-10", closure_status="closed", document=_daily_document(), evidence_groups=[EvidenceGroup("evg_a", "local", ("source",), ("daily_note",), {})], quality_status="complete")
    mark_file_published(conn, revision.revision_id, artifact, full_file_sha256(artifact))
    finalize_revision(conn, revision.revision_id)
    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no Markdown reads")))

    result = resolve_lower_revisions(conn=conn, level="weekly", period_start="2026-07-06", period_end="2026-07-12", coverage_end="2026-07-10", deployment_start="2026-07-01")

    assert [row.revision_id for row in result] == [revision.revision_id]
