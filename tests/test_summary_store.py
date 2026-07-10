from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest


DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

from schema_migrations import ensure_summary_revision_schema  # noqa: E402
from source_ingest_store import get_db_connection  # noqa: E402
from summary_contracts import EvidenceGroup  # noqa: E402
from summary_store import (  # noqa: E402
    SummaryStoreError,
    ensure_logical_summary,
    find_published_revision,
    finalize_revision,
    load_revision_document,
    logical_summary_id,
    mark_file_published,
    stage_revision,
)


def valid_daily_document(*, headline: str = "完成结构化总结设计。") -> dict:
    return {
        "contract_version": "summary-v1",
        "taxonomy_version": "dimensions-v1",
        "policy_version": "summary-policy-v1",
        "level": "daily",
        "period": "2026-07-10",
        "headline": headline,
        "items": [
            {
                "item_type": "decision",
                "title": "统一入口",
                "conclusion": "所有周期总结通过 lifecycle manager。",
                "value": "消除双路径漂移。",
                "dimensions": ["计划组织", "专业知识"],
                "evidence_group_ids": ["evg_a"],
                "confidence": 0.95,
            }
        ],
    }


def valid_evidence_groups() -> tuple[EvidenceGroup, ...]:
    return (
        EvidenceGroup(
            evidence_group_id="evg_a",
            evidence_kind="work",
            source_refs=("record:rec_a", "commit:abc123"),
            source_kinds=("record", "git"),
            payload={"claim": "统一总结入口"},
        ),
    )


@pytest.fixture
def conn(tmp_path: Path):
    connection = get_db_connection(tmp_path / "agent_history.db")
    try:
        yield connection
    finally:
        connection.close()


def stage_daily(conn: sqlite3.Connection, *, digest: str = "digest-1"):
    summary_id = ensure_logical_summary(conn, "daily", "2026-07-10")
    return stage_revision(
        conn,
        summary_id=summary_id,
        input_digest=digest,
        coverage_start="2026-07-10",
        coverage_end="2026-07-10",
        closure_status="closed",
        document=valid_daily_document(),
        evidence_groups=valid_evidence_groups(),
        quality_status="complete",
    )


def test_logical_summary_identity_is_stable_and_unique(conn: sqlite3.Connection):
    first = ensure_logical_summary(conn, "daily", "2026-07-10")
    second = ensure_logical_summary(conn, "daily", "2026-07-10")

    assert first == second == logical_summary_id("daily", "2026-07-10")
    assert conn.execute("SELECT count(*) FROM summaries").fetchone()[0] == 1


def test_stage_revision_is_idempotent_for_same_input(conn: sqlite3.Connection):
    first = stage_daily(conn)
    second = stage_revision(
        conn,
        summary_id=first.summary_id,
        input_digest="digest-1",
        coverage_start="2026-07-10",
        coverage_end="2026-07-10",
        closure_status="closed",
        document=valid_daily_document(headline="不得覆盖 immutable revision"),
        evidence_groups=valid_evidence_groups(),
        quality_status="complete",
    )

    assert first.revision_id == second.revision_id
    assert conn.execute("SELECT count(*) FROM summary_revisions").fetchone()[0] == 1
    assert load_revision_document(conn, first.revision_id)["headline"] == "完成结构化总结设计。"


def test_stage_revision_persists_items_dimensions_and_evidence(conn: sqlite3.Connection):
    revision = stage_daily(conn)

    item = conn.execute(
        "SELECT item_id, revision_id, section_key, ordinal FROM summary_items"
    ).fetchone()
    dimensions = conn.execute(
        "SELECT dimension, position FROM summary_item_dimensions ORDER BY position"
    ).fetchall()
    sources = conn.execute(
        "SELECT source_kind, source_ref FROM summary_evidence_sources ORDER BY source_ref"
    ).fetchall()
    link = conn.execute(
        "SELECT item_id, revision_id, evidence_group_id FROM summary_item_evidence"
    ).fetchone()

    assert item["revision_id"] == revision.revision_id
    assert (item["section_key"], item["ordinal"]) == ("work_progress", 1)
    assert [(row["dimension"], row["position"]) for row in dimensions] == [
        ("计划组织", 1),
        ("专业知识", 2),
    ]
    assert {(row["source_kind"], row["source_ref"]) for row in sources} == {
        ("record", "record:rec_a"),
        ("git", "commit:abc123"),
    }
    assert (link["item_id"], link["revision_id"], link["evidence_group_id"]) == (
        item["item_id"],
        revision.revision_id,
        "evg_a",
    )


def test_finalize_requires_file_published_state(conn: sqlite3.Connection):
    revision = stage_daily(conn)

    with pytest.raises(SummaryStoreError, match="file_published"):
        finalize_revision(conn, revision.revision_id)

    current = conn.execute(
        "SELECT current_revision_id FROM summaries WHERE summary_id = ?", (revision.summary_id,)
    ).fetchone()[0]
    assert current is None


def test_finalize_switches_current_only_after_full_file_hash_matches(
    conn: sqlite3.Connection, tmp_path: Path
):
    revision = stage_daily(conn)
    artifact = tmp_path / "2026-07-10.md"
    artifact.write_bytes(b"---\nrevision_id: test\n---\nsummary\n")
    import hashlib

    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    mark_file_published(conn, revision.revision_id, artifact, artifact_hash)
    finalized = finalize_revision(conn, revision.revision_id)

    row = conn.execute(
        "SELECT current_revision_id FROM summaries WHERE summary_id = ?", (revision.summary_id,)
    ).fetchone()
    assert finalized.publish_status == "published"
    assert row[0] == revision.revision_id
    assert find_published_revision(conn, revision.summary_id, "digest-1") == finalized


def test_mark_file_published_rejects_wrong_hash(conn: sqlite3.Connection, tmp_path: Path):
    revision = stage_daily(conn)
    artifact = tmp_path / "2026-07-10.md"
    artifact.write_text("summary", encoding="utf-8")

    with pytest.raises(SummaryStoreError, match="hash"):
        mark_file_published(conn, revision.revision_id, artifact, "0" * 64)

    assert conn.execute(
        "SELECT publish_status FROM summary_revisions WHERE revision_id = ?",
        (revision.revision_id,),
    ).fetchone()[0] == "staged"


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def legacy_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE summary_runs (
            id TEXT PRIMARY KEY,
            summary_level TEXT NOT NULL,
            period_id TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            source_mode TEXT NOT NULL,
            status TEXT NOT NULL,
            output_path TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE summary_run_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(run_id) REFERENCES summary_runs(id) ON DELETE CASCADE
        );
        """
    )
    conn.execute(
        """
        INSERT INTO summary_runs VALUES
            ('sum_old', 'weekly', '2026-W28', '2026-07-06', '2026-07-12',
             'daily-first', 'completed', '70_Summaries/Weekly/2026-W28.md',
             '{"warning": "legacy"}', '2026-07-12T18:00:00', '2026-07-12T18:01:00')
        """
    )
    conn.execute(
        """
        INSERT INTO summary_run_sources
            (run_id, source_kind, source_ref, metadata_json)
        VALUES ('sum_old', 'daily', '10_Periodic/Daily/2026-07-10.md', '{"score": 1}')
        """
    )
    conn.commit()
    return conn


def test_migration_converts_legacy_rows_and_drops_old_tables(tmp_path: Path):
    conn = legacy_connection(tmp_path / "legacy.db")
    try:
        ensure_summary_revision_schema(conn)

        summary = conn.execute("SELECT * FROM summaries").fetchone()
        revision = conn.execute("SELECT * FROM summary_revisions").fetchone()
        source = conn.execute("SELECT * FROM summary_evidence_sources").fetchone()

        assert not table_exists(conn, "summary_runs")
        assert not table_exists(conn, "summary_run_sources")
        assert summary["current_revision_id"] == revision["revision_id"]
        assert (revision["contract_version"], revision["publish_status"]) == (
            "legacy",
            "published",
        )
        assert json.loads(revision["metadata_json"])["legacy_run_id"] == "sum_old"
        assert (source["source_kind"], source["source_ref"]) == (
            "daily",
            "10_Periodic/Daily/2026-07-10.md",
        )

        ensure_summary_revision_schema(conn)
        assert conn.execute("SELECT count(*) FROM summary_revisions").fetchone()[0] == 1
    finally:
        conn.close()


def test_schema_enforces_foreign_keys_and_unique_input(conn: sqlite3.Connection):
    summary_id = ensure_logical_summary(conn, "daily", "2026-07-10")
    stage_daily(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO summary_revisions
                (revision_id, summary_id, input_digest, coverage_start, coverage_end,
                 closure_status, contract_version, taxonomy_version, policy_version,
                 publish_status, quality_status, document_json, artifact_path,
                 metadata_json, created_at)
            VALUES ('rev_other', ?, 'digest-1', '2026-07-10', '2026-07-10', 'closed',
                    'summary-v1', 'dimensions-v1', 'summary-policy-v1', 'staged',
                    'complete', '{}', '', '{}', '2026-07-10T18:00:00')
            """,
            (summary_id,),
        )
    conn.rollback()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO summary_item_support (item_id, supporting_item_id) VALUES ('missing', 'also_missing')"
        )
    conn.rollback()
