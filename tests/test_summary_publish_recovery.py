from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest


DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

from source_ingest_store import get_db_connection  # noqa: E402
from summary_contracts import EvidenceGroup  # noqa: E402
from summary_store import (  # noqa: E402
    SummaryStoreError,
    ensure_logical_summary,
    mark_file_published,
    recover_pending_revision,
    stage_revision,
)


@pytest.fixture
def conn(tmp_path: Path):
    connection = get_db_connection(tmp_path / "agent_history.db")
    try:
        yield connection
    finally:
        connection.close()


def staged_revision(conn: sqlite3.Connection):
    summary_id = ensure_logical_summary(conn, "daily", "2026-07-10")
    document = {
        "contract_version": "summary-v1",
        "taxonomy_version": "dimensions-v1",
        "policy_version": "summary-policy-v1",
        "level": "daily",
        "period": "2026-07-10",
        "headline": "完成结构化总结设计。",
        "items": [
            {
                "item_type": "decision",
                "title": "统一入口",
                "conclusion": "统一总结入口。",
                "value": "消除漂移。",
                "dimensions": ["计划组织"],
                "evidence_group_ids": ["evg_a"],
                "confidence": 0.9,
            }
        ],
    }
    evidence = (
        EvidenceGroup("evg_a", "work", ("record:rec_a",), ("record",), {"claim": "x"}),
    )
    return stage_revision(
        conn,
        summary_id=summary_id,
        input_digest="digest-1",
        coverage_start="2026-07-10",
        coverage_end="2026-07-10",
        closure_status="closed",
        document=document,
        evidence_groups=evidence,
        quality_status="complete",
    )


def write_artifact(path: Path, revision_id: str, input_digest: str) -> str:
    path.write_text(
        f"---\nrevision_id: {revision_id}\ninput_digest: {input_digest}\n---\n\n# Summary\n",
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_staged_revision_without_matching_file_requests_rerender(
    conn: sqlite3.Connection, tmp_path: Path
):
    revision = staged_revision(conn)

    result = recover_pending_revision(conn, revision.revision_id, tmp_path / "missing.md")

    assert result.action == "rerender"
    assert result.revision.publish_status == "staged"


def test_recovery_finalizes_file_replaced_before_db_update(
    conn: sqlite3.Connection, tmp_path: Path
):
    revision = staged_revision(conn)
    artifact = tmp_path / "2026-07-10.md"
    write_artifact(artifact, revision.revision_id, revision.input_digest)

    result = recover_pending_revision(conn, revision.revision_id, artifact)

    assert result.action == "finalized"
    assert result.revision.publish_status == "published"
    assert conn.execute("SELECT current_revision_id FROM summaries").fetchone()[0] == revision.revision_id


def test_recovery_finalizes_file_published_revision(conn: sqlite3.Connection, tmp_path: Path):
    revision = staged_revision(conn)
    artifact = tmp_path / "2026-07-10.md"
    artifact_hash = write_artifact(artifact, revision.revision_id, revision.input_digest)
    mark_file_published(conn, revision.revision_id, artifact, artifact_hash)

    result = recover_pending_revision(conn, revision.revision_id)

    assert result.action == "finalized"
    assert result.revision.publish_status == "published"


def test_recovery_rejects_file_for_another_revision(conn: sqlite3.Connection, tmp_path: Path):
    revision = staged_revision(conn)
    artifact = tmp_path / "2026-07-10.md"
    write_artifact(artifact, "rev_unknown", revision.input_digest)

    with pytest.raises(SummaryStoreError, match="revision marker"):
        recover_pending_revision(conn, revision.revision_id, artifact)


def test_file_published_recovery_rejects_tampered_full_file(
    conn: sqlite3.Connection, tmp_path: Path
):
    revision = staged_revision(conn)
    artifact = tmp_path / "2026-07-10.md"
    artifact_hash = write_artifact(artifact, revision.revision_id, revision.input_digest)
    mark_file_published(conn, revision.revision_id, artifact, artifact_hash)
    artifact.write_text(artifact.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")

    with pytest.raises(SummaryStoreError, match="hash"):
        recover_pending_revision(conn, revision.revision_id)
