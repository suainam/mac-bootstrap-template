from __future__ import annotations

import sys
from pathlib import Path

import pytest

DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

from db_helper import get_db_connection
from summary_contracts import EvidenceGroup, SummaryDocument
from summary_inputs import MissingLowerCoverageError, previous_level, resolve_lower_revisions
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

    result = resolve_lower_revisions(conn=conn, level="weekly", period_start="2026-07-06", period_end="2026-07-12", coverage_end="2026-07-10", deployment_start="2026-07-10")

    assert [row.revision_id for row in result] == [revision.revision_id]


def test_resolve_lower_revisions_rejects_missing_workday_coverage(tmp_path):
    conn = get_db_connection(tmp_path / "missing.sqlite")

    with pytest.raises(MissingLowerCoverageError, match="2026-07-09"):
        resolve_lower_revisions(
            conn=conn,
            level="weekly",
            period_start="2026-07-06",
            period_end="2026-07-12",
            coverage_end="2026-07-10",
            deployment_start="2026-07-09",
        )


def test_boundary_replay_selects_exact_historical_lower_revision(tmp_path):
    conn = get_db_connection(tmp_path / "boundary.sqlite")
    summary_id = ensure_logical_summary(conn, "weekly", "2026-W31")
    document = _daily_document()
    document_dict = document.to_dict()
    document_dict["level"] = "weekly"
    document_dict["period"] = "2026-W31"
    exact = stage_revision(
        conn,
        summary_id=summary_id,
        input_digest="exact-boundary",
        coverage_start="2026-07-27",
        coverage_end="2026-07-31",
        closure_status="provisional",
        document=document_dict,
        evidence_groups=[EvidenceGroup("evg_a", "local", ("source",), ("daily_note",), {})],
        quality_status="complete",
    )
    exact_file = tmp_path / "weekly-exact.md"
    exact_file.write_text("exact", encoding="utf-8")
    mark_file_published(conn, exact.revision_id, exact_file, full_file_sha256(exact_file))
    finalize_revision(conn, exact.revision_id)
    conn.execute(
        "UPDATE summary_revisions SET published_at = '2026-07-31T18:00:00' WHERE revision_id = ?",
        (exact.revision_id,),
    )
    conn.commit()
    later = stage_revision(
        conn,
        summary_id=summary_id,
        input_digest="later-coverage",
        coverage_start="2026-07-27",
        coverage_end="2026-08-02",
        closure_status="closed",
        document=document_dict,
        evidence_groups=[EvidenceGroup("evg_a", "local", ("source",), ("daily_note",), {})],
        quality_status="complete",
    )
    later_file = tmp_path / "weekly-later.md"
    later_file.write_text("later", encoding="utf-8")
    mark_file_published(conn, later.revision_id, later_file, full_file_sha256(later_file))
    finalize_revision(conn, later.revision_id)
    later_exact = stage_revision(
        conn,
        summary_id=summary_id,
        input_digest="later-exact-boundary",
        coverage_start="2026-07-27",
        coverage_end="2026-07-31",
        closure_status="provisional",
        document=document_dict,
        evidence_groups=[EvidenceGroup("evg_a", "local", ("source",), ("daily_note",), {})],
        quality_status="complete",
    )
    later_exact_file = tmp_path / "weekly-later-exact.md"
    later_exact_file.write_text("later exact", encoding="utf-8")
    mark_file_published(
        conn,
        later_exact.revision_id,
        later_exact_file,
        full_file_sha256(later_exact_file),
    )
    finalize_revision(conn, later_exact.revision_id)
    conn.execute(
        "UPDATE summary_revisions SET published_at = '2026-08-03T18:00:00' WHERE revision_id = ?",
        (later_exact.revision_id,),
    )
    conn.commit()

    selected = resolve_lower_revisions(
        conn=conn,
        level="monthly",
        period_start="2026-07-01",
        period_end="2026-07-31",
        coverage_end="2026-07-31",
        deployment_start="2026-07-27",
        preferred_revision_ids={exact.revision_id},
    )

    assert [revision.revision_id for revision in selected] == [exact.revision_id]
