"""Immutable SQLite store and recoverable publish state for structured summaries."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from summary_contracts import EvidenceGroup, SummaryDocument, canonical_json


SUMMARY_LEVELS = {"daily", "weekly", "monthly", "quarterly", "yearly"}


class SummaryStoreError(RuntimeError):
    """Raised when a revision violates persistence or publish state rules."""


@dataclass(frozen=True)
class SummaryRevision:
    revision_id: str
    summary_id: str
    input_digest: str
    coverage_start: str
    coverage_end: str
    closure_status: str
    contract_version: str
    taxonomy_version: str
    policy_version: str
    publish_status: str
    quality_status: str
    artifact_path: str
    artifact_hash: str | None
    created_at: str
    published_at: str | None


@dataclass(frozen=True)
class RecoveryResult:
    action: str
    revision: SummaryRevision


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stable_id(prefix: str, value: str, length: int) -> str:
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def logical_summary_id(level: str, period_id: str) -> str:
    return _stable_id("summary_", f"{level}:{period_id}", 20)


def revision_id(summary_id: str, input_digest: str) -> str:
    return _stable_id("rev_", f"{summary_id}:{input_digest}", 24)


def item_id(revision_id_value: str, section_key: str, ordinal: int) -> str:
    return _stable_id("item_", f"{revision_id_value}:{section_key}:{ordinal}", 24)


def _row_to_revision(row: sqlite3.Row) -> SummaryRevision:
    return SummaryRevision(
        revision_id=str(row["revision_id"]),
        summary_id=str(row["summary_id"]),
        input_digest=str(row["input_digest"]),
        coverage_start=str(row["coverage_start"]),
        coverage_end=str(row["coverage_end"]),
        closure_status=str(row["closure_status"]),
        contract_version=str(row["contract_version"]),
        taxonomy_version=str(row["taxonomy_version"]),
        policy_version=str(row["policy_version"]),
        publish_status=str(row["publish_status"]),
        quality_status=str(row["quality_status"]),
        artifact_path=str(row["artifact_path"]),
        artifact_hash=None if row["artifact_hash"] is None else str(row["artifact_hash"]),
        created_at=str(row["created_at"]),
        published_at=None if row["published_at"] is None else str(row["published_at"]),
    )


def _get_revision(conn: sqlite3.Connection, revision_id_value: str) -> SummaryRevision:
    row = conn.execute(
        "SELECT * FROM summary_revisions WHERE revision_id = ?", (revision_id_value,)
    ).fetchone()
    if row is None:
        raise SummaryStoreError(f"unknown summary revision: {revision_id_value}")
    return _row_to_revision(row)


def ensure_logical_summary(conn: sqlite3.Connection, level: str, period_id: str) -> str:
    if level not in SUMMARY_LEVELS:
        raise SummaryStoreError(f"unsupported summary level: {level}")
    summary_id = logical_summary_id(level, period_id)
    now = now_iso()
    with conn:
        conn.execute(
            """
            INSERT INTO summaries
                (summary_id, summary_level, period_id, current_revision_id, created_at, updated_at)
            VALUES (?, ?, ?, NULL, ?, ?)
            ON CONFLICT(summary_level, period_id) DO NOTHING
            """,
            (summary_id, level, period_id, now, now),
        )
    row = conn.execute(
        "SELECT summary_id FROM summaries WHERE summary_level = ? AND period_id = ?",
        (level, period_id),
    ).fetchone()
    return str(row[0])


def _document_dict(document: SummaryDocument | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(document, SummaryDocument):
        return document.to_dict()
    return dict(document)


def _section_key(item: Mapping[str, Any]) -> str:
    item_type_value = str(item["item_type"])
    if item_type_value == "insight":
        return "knowledge_insight"
    if item_type_value in {"risk", "action"}:
        return "risks_actions"
    return "work_progress"


def _insert_evidence_groups(
    conn: sqlite3.Connection,
    revision_id_value: str,
    evidence_groups: Iterable[EvidenceGroup],
) -> set[str]:
    group_ids: set[str] = set()
    for group in evidence_groups:
        if group.evidence_group_id in group_ids:
            raise SummaryStoreError(f"duplicate evidence group: {group.evidence_group_id}")
        if len(group.source_refs) != len(group.source_kinds):
            raise SummaryStoreError(
                f"evidence source refs/kinds length mismatch: {group.evidence_group_id}"
            )
        group_ids.add(group.evidence_group_id)
        conn.execute(
            """
            INSERT INTO summary_evidence_groups
                (revision_id, evidence_group_id, evidence_kind, normalized_payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                revision_id_value,
                group.evidence_group_id,
                group.evidence_kind,
                canonical_json(group.payload),
            ),
        )
        for source_ref, source_kind in zip(group.source_refs, group.source_kinds, strict=True):
            conn.execute(
                """
                INSERT INTO summary_evidence_sources
                    (revision_id, evidence_group_id, source_kind, source_ref,
                     source_claim_id, metadata_json)
                VALUES (?, ?, ?, ?, '', '{}')
                """,
                (revision_id_value, group.evidence_group_id, source_kind, source_ref),
            )
    return group_ids


def _insert_items(
    conn: sqlite3.Connection,
    revision_id_value: str,
    document: Mapping[str, Any],
    evidence_group_ids: set[str],
) -> None:
    ordinals: defaultdict[str, int] = defaultdict(int)
    for item in document["items"]:
        section_key = _section_key(item)
        ordinals[section_key] += 1
        ordinal = ordinals[section_key]
        item_id_value = item_id(revision_id_value, section_key, ordinal)
        referenced_groups = set(item["evidence_group_ids"])
        unknown_groups = referenced_groups - evidence_group_ids
        if unknown_groups:
            raise SummaryStoreError(f"item references unknown evidence groups: {sorted(unknown_groups)}")
        conn.execute(
            """
            INSERT INTO summary_items
                (item_id, revision_id, section_key, ordinal, item_type, title, conclusion,
                 value, trend, period_change, lower_summary_refs_json, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id_value,
                revision_id_value,
                section_key,
                ordinal,
                str(item["item_type"]),
                str(item["title"]),
                str(item["conclusion"]),
                str(item["value"]),
                item.get("trend"),
                item.get("period_change"),
                canonical_json(item.get("lower_summary_refs", [])),
                float(item["confidence"]),
            ),
        )
        for position, dimension in enumerate(item["dimensions"], start=1):
            conn.execute(
                """
                INSERT INTO summary_item_dimensions
                    (item_id, dimension, position, taxonomy_version)
                VALUES (?, ?, ?, ?)
                """,
                (item_id_value, dimension, position, document["taxonomy_version"]),
            )
        for evidence_group_id in sorted(referenced_groups):
            conn.execute(
                """
                INSERT INTO summary_item_evidence (item_id, revision_id, evidence_group_id)
                VALUES (?, ?, ?)
                """,
                (item_id_value, revision_id_value, evidence_group_id),
            )
        for supporting_item_id in item.get("supporting_item_ids", []):
            conn.execute(
                """
                INSERT INTO summary_item_support (item_id, supporting_item_id)
                VALUES (?, ?)
                """,
                (item_id_value, supporting_item_id),
            )


def stage_revision(
    conn: sqlite3.Connection,
    *,
    summary_id: str,
    input_digest: str,
    coverage_start: str,
    coverage_end: str,
    closure_status: str,
    document: SummaryDocument | Mapping[str, Any],
    evidence_groups: Iterable[EvidenceGroup],
    quality_status: str,
    metadata: Mapping[str, Any] | None = None,
) -> SummaryRevision:
    """Stage an immutable revision, or return the existing same-input revision unchanged."""

    existing = conn.execute(
        "SELECT * FROM summary_revisions WHERE summary_id = ? AND input_digest = ?",
        (summary_id, input_digest),
    ).fetchone()
    if existing is not None:
        return _row_to_revision(existing)

    if conn.execute("SELECT 1 FROM summaries WHERE summary_id = ?", (summary_id,)).fetchone() is None:
        raise SummaryStoreError(f"unknown logical summary: {summary_id}")
    if closure_status not in {"provisional", "closed"}:
        raise SummaryStoreError(f"invalid closure status: {closure_status}")
    if quality_status not in {"complete", "degraded"}:
        raise SummaryStoreError(f"invalid quality status: {quality_status}")

    value = _document_dict(document)
    revision_id_value = revision_id(summary_id, input_digest)
    created_at = now_iso()
    with conn:
        conn.execute(
            """
            INSERT INTO summary_revisions
                (revision_id, summary_id, input_digest, coverage_start, coverage_end,
                 closure_status, contract_version, taxonomy_version, policy_version,
                 publish_status, quality_status, document_json, artifact_path, artifact_hash,
                 metadata_json, created_at, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'staged', ?, ?, '', NULL, ?, ?, NULL)
            """,
            (
                revision_id_value,
                summary_id,
                input_digest,
                coverage_start,
                coverage_end,
                closure_status,
                value["contract_version"],
                value["taxonomy_version"],
                value["policy_version"],
                quality_status,
                canonical_json(value),
                canonical_json(dict(metadata or {})),
                created_at,
            ),
        )
        group_ids = _insert_evidence_groups(conn, revision_id_value, evidence_groups)
        _insert_items(conn, revision_id_value, value, group_ids)
    return _get_revision(conn, revision_id_value)


def load_revision_document(conn: sqlite3.Connection, revision_id_value: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT document_json FROM summary_revisions WHERE revision_id = ?", (revision_id_value,)
    ).fetchone()
    if row is None:
        raise SummaryStoreError(f"unknown summary revision: {revision_id_value}")
    value = json.loads(row[0])
    if not isinstance(value, dict):
        raise SummaryStoreError(f"invalid stored document: {revision_id_value}")
    return value


def find_published_revision(
    conn: sqlite3.Connection, summary_id: str, input_digest: str
) -> SummaryRevision | None:
    row = conn.execute(
        """
        SELECT * FROM summary_revisions
        WHERE summary_id = ? AND input_digest = ? AND publish_status = 'published'
        """,
        (summary_id, input_digest),
    ).fetchone()
    return None if row is None else _row_to_revision(row)


def full_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mark_file_published(
    conn: sqlite3.Connection,
    revision_id_value: str,
    artifact_path: Path,
    artifact_hash: str,
) -> SummaryRevision:
    revision = _get_revision(conn, revision_id_value)
    if revision.publish_status == "file_published":
        if revision.artifact_path == str(artifact_path) and revision.artifact_hash == artifact_hash:
            return revision
        raise SummaryStoreError(f"file_published revision metadata mismatch: {revision_id_value}")
    if revision.publish_status != "staged":
        raise SummaryStoreError(
            f"revision must be staged before file_published: {revision.publish_status}"
        )
    if not artifact_path.is_file():
        raise SummaryStoreError(f"artifact does not exist: {artifact_path}")
    actual_hash = full_file_sha256(artifact_path)
    if actual_hash != artifact_hash:
        raise SummaryStoreError(
            f"artifact hash mismatch for {revision_id_value}: expected {artifact_hash}, got {actual_hash}"
        )
    with conn:
        conn.execute(
            """
            UPDATE summary_revisions
            SET publish_status = 'file_published', artifact_path = ?, artifact_hash = ?
            WHERE revision_id = ? AND publish_status = 'staged'
            """,
            (str(artifact_path), artifact_hash, revision_id_value),
        )
    return _get_revision(conn, revision_id_value)


def finalize_revision(conn: sqlite3.Connection, revision_id_value: str) -> SummaryRevision:
    revision = _get_revision(conn, revision_id_value)
    if revision.publish_status == "published":
        return revision
    if revision.publish_status != "file_published":
        raise SummaryStoreError(
            f"revision must be file_published before finalize: {revision.publish_status}"
        )
    artifact_path = Path(revision.artifact_path)
    if not artifact_path.is_file():
        raise SummaryStoreError(f"published artifact does not exist: {artifact_path}")
    actual_hash = full_file_sha256(artifact_path)
    if actual_hash != revision.artifact_hash:
        raise SummaryStoreError(
            f"artifact hash mismatch for {revision_id_value}: expected {revision.artifact_hash}, got {actual_hash}"
        )
    published_at = now_iso()
    with conn:
        conn.execute(
            """
            UPDATE summary_revisions
            SET publish_status = 'published', published_at = ?
            WHERE revision_id = ? AND publish_status = 'file_published'
            """,
            (published_at, revision_id_value),
        )
        conn.execute(
            """
            UPDATE summaries
            SET current_revision_id = ?, updated_at = ?
            WHERE summary_id = ?
            """,
            (revision_id_value, published_at, revision.summary_id),
        )
    return _get_revision(conn, revision_id_value)


def mark_revision_failed(conn: sqlite3.Connection, revision_id_value: str) -> SummaryRevision:
    revision = _get_revision(conn, revision_id_value)
    if revision.publish_status not in {"staged", "file_published"}:
        raise SummaryStoreError(f"cannot fail revision in state: {revision.publish_status}")
    with conn:
        conn.execute(
            "UPDATE summary_revisions SET publish_status = 'failed' WHERE revision_id = ?",
            (revision_id_value,),
        )
    return _get_revision(conn, revision_id_value)


def _artifact_markers(path: Path) -> tuple[str | None, str | None]:
    revision_marker = None
    digest_marker = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
        if line.startswith("revision_id:"):
            revision_marker = line.partition(":")[2].strip().strip('"\'')
        elif line.startswith("input_digest:"):
            digest_marker = line.partition(":")[2].strip().strip('"\'')
    return revision_marker, digest_marker


def recover_pending_revision(
    conn: sqlite3.Connection,
    revision_id_value: str,
    artifact_path: Path | None = None,
) -> RecoveryResult:
    """Finalize a matching replaced file, or tell the renderer to publish the staged payload."""

    revision = _get_revision(conn, revision_id_value)
    if revision.publish_status == "published":
        return RecoveryResult("already_published", revision)
    if revision.publish_status == "failed":
        raise SummaryStoreError(f"cannot recover failed revision: {revision_id_value}")
    if revision.publish_status == "file_published":
        return RecoveryResult("finalized", finalize_revision(conn, revision_id_value))

    candidate = artifact_path
    if candidate is None or not candidate.is_file():
        return RecoveryResult("rerender", revision)
    revision_marker, digest_marker = _artifact_markers(candidate)
    if revision_marker is None:
        return RecoveryResult("rerender", revision)
    if revision_marker != revision_id_value:
        known = conn.execute(
            "SELECT 1 FROM summary_revisions WHERE revision_id = ?", (revision_marker,)
        ).fetchone()
        if known is not None:
            return RecoveryResult("rerender", revision)
        raise SummaryStoreError(f"artifact has unknown revision marker: {revision_marker}")
    if digest_marker != revision.input_digest:
        raise SummaryStoreError(
            f"artifact input digest marker mismatch for revision: {revision_id_value}"
        )
    artifact_hash = full_file_sha256(candidate)
    mark_file_published(conn, revision_id_value, candidate, artifact_hash)
    return RecoveryResult("finalized", finalize_revision(conn, revision_id_value))
