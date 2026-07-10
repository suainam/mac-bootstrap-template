"""Thin revisioned Summary Engine orchestration."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from data_hub_config import get_runtime_config, get_summary_output_dir
from db_helper import get_db_connection
from llm_filter import call_llm_raw
from summary_contracts import EvidenceGroup, build_input_digest, load_contract_bundle
from summary_evidence import collect_summary_evidence
from summary_inputs import previous_level, resolve_lower_revisions
from summary_renderer import render_summary_markdown
from summary_store import (
    ensure_logical_summary,
    finalize_revision,
    find_published_revision,
    full_file_sha256,
    mark_file_published,
    stage_revision,
)
from summary_synthesis import synthesize_summary

CURRENT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = CURRENT_DIR / "scripts"
import sys
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from knowledge_retrieval import build_retrieval_packet, make_llm_wiki_client


@dataclass(frozen=True)
class PeriodCoverage:
    period_id: str
    period_start: str
    period_end: str
    coverage_end: str
    closure_status: str


@dataclass(frozen=True)
class SummaryBuildResult:
    output_path: Path
    revision_id: str
    quality_status: str
    warnings: tuple[str, ...]


class RuntimeBackend:
    def generate(self, prompt: str) -> str:
        return call_llm_raw(prompt)


def resolve_period_coverage(level: str, anchor_date: str) -> PeriodCoverage:
    current = datetime.strptime(anchor_date, "%Y-%m-%d").date()
    if level == "daily":
        start = end = current
        coverage_end = current
    elif level == "weekly":
        start = current - timedelta(days=current.weekday())
        end = start + timedelta(days=6)
        coverage_end = min(current, end)
    elif level == "monthly":
        start = current.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        coverage_end = min(current, end)
    elif level == "quarterly":
        quarter = (current.month - 1) // 3 + 1
        start = date(current.year, 3 * quarter - 2, 1)
        end = date(current.year + 1, 1, 1) - timedelta(days=1) if quarter == 4 else date(current.year, 3 * quarter + 1, 1) - timedelta(days=1)
        coverage_end = min(current, end)
    elif level == "yearly":
        start, end, coverage_end = date(current.year, 1, 1), date(current.year, 12, 31), current
    else:
        raise ValueError(f"unsupported summary level: {level}")
    period_id = current.isoformat() if level == "daily" else (
        f"{start.isocalendar().year}-W{start.isocalendar().week:02d}" if level == "weekly" else
        f"{current.year}-{current.month:02d}" if level == "monthly" else
        f"{current.year}-Q{(current.month - 1) // 3 + 1}" if level == "quarterly" else str(current.year)
    )
    return PeriodCoverage(period_id, start.isoformat(), end.isoformat(), coverage_end.isoformat(), "closed" if coverage_end == end else "provisional")


def _write_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _sqlite_evidence(conn: sqlite3.Connection, start: str, end: str) -> dict[str, list[dict[str, Any]]]:
    records = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, status, record_type, title, content, candidate_date, project
            FROM knowledge_records
            WHERE status = 'accepted' AND candidate_date BETWEEN ? AND ?
            ORDER BY candidate_date, id
            """,
            (start, end),
        ).fetchall()
    ]
    candidates = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, status, candidate_type, title, content, candidate_date
            FROM knowledge_candidates
            WHERE status = 'accepted' AND candidate_date BETWEEN ? AND ?
            ORDER BY candidate_date, id
            """,
            (start, end),
        ).fetchall()
    ]
    return {"knowledge_records": records, "accepted_candidates": candidates}


def _git_repositories(roots: list[Path]) -> list[Path]:
    repositories: set[Path] = set()
    for root in roots:
        if (root / ".git").exists():
            repositories.add(root)
        if root.is_dir():
            repositories.update(path.parent for path in root.glob("*/.git"))
    return sorted(repositories)


def _git_evidence(roots: list[Path], start: str, end: str) -> list[dict[str, Any]]:
    until = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
    commits: list[dict[str, Any]] = []
    for repository in _git_repositories(roots):
        result = subprocess.run(
            [
                "git", "-C", str(repository), "log",
                f"--since={start}T00:00:00", f"--until={until.strftime('%Y-%m-%d')}T00:00:00",
                "--pretty=format:%H%x1f%aI%x1f%s",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            parts = line.split("\x1f", 2)
            if len(parts) != 3:
                continue
            commit_hash, authored_at, subject = parts
            commits.append(
                {
                    "hash": commit_hash,
                    "authored_at": authored_at,
                    "subject": subject,
                    "repository": repository.name,
                    "source_ref": f"commit:{repository.name}:{commit_hash}",
                }
            )
    return sorted(commits, key=lambda item: (item["authored_at"], item["source_ref"]))


def build_period_summary(
    level: str,
    anchor_date: str,
    *,
    backend: Any | None = None,
    retrieval_packet: dict[str, Any] | None = None,
    llm_wiki_client: Any | None = None,
) -> SummaryBuildResult:
    coverage = resolve_period_coverage(level, anchor_date)
    config = get_runtime_config()
    conn = get_db_connection()
    try:
        packet = retrieval_packet or build_retrieval_packet(
            task_goal=f"{level} summary {coverage.period_id}", keywords=[coverage.period_id],
            date_from=coverage.period_start, date_to=coverage.coverage_end, include_llm_wiki=True,
        )
        if retrieval_packet is None:
            packet = dict(packet)
            packet.update(_sqlite_evidence(conn, coverage.period_start, coverage.coverage_end))
            packet["git_commits"] = _git_evidence(
                config.paths.git_search_roots,
                coverage.period_start,
                coverage.coverage_end,
            )
        evidence = collect_summary_evidence(
            level=level, period=coverage.period_id, query=f"{level} summary {coverage.period_id}",
            retrieval_packet=packet, llm_wiki_client=llm_wiki_client if llm_wiki_client is not None else make_llm_wiki_client(),
        )
        lower = [] if level == "daily" else resolve_lower_revisions(
            conn=conn, level=level, period_start=coverage.period_start, period_end=coverage.period_end,
            coverage_end=coverage.coverage_end, deployment_start=config.summary.deployment_start,
        )
        evidence["lower_item_ids"] = []
        for item in lower:
            artifact_path = Path(item.artifact_path) if item.artifact_path else None
            try:
                ref = str(artifact_path.relative_to(config.paths.vault_dir)) if artifact_path else ""
            except ValueError:
                ref = ""
            if not ref:
                lower_level = previous_level(level)
                ref = f"{config.summary.root_relative}/{config.summary.level_dirs[lower_level]}/{item.period_id}.md"
            evidence["evidence_groups"].append({
                "evidence_group_id": f"evg_lower_{item.revision_id.removeprefix('rev_')}",
                "evidence_kind": "lower_revision", "source_refs": [ref], "source_kinds": ["lower_revision"],
                "payload": {"revision_id": item.revision_id, "period_id": item.period_id, "item_ids": item.item_ids},
            })
            evidence["lower_item_ids"].extend(item.item_ids)
        evidence["evidence_groups"].sort(key=lambda group: group["evidence_group_id"])
        bundle = load_contract_bundle()
        digest = build_input_digest(level=level, period=coverage.period_id, evidence_packet=evidence, bundle=bundle,
                                    prompt=(CURRENT_DIR / "prompts" / ({"daily":"daily-summary.md", "weekly":"weekly-summary.md"}.get(level, "higher-period-summary.md"))).read_text(encoding="utf-8"),
                                    backend_kind=type(backend or RuntimeBackend()).__name__, model="configured")
        summary_id = ensure_logical_summary(conn, level, coverage.period_id)
        existing = find_published_revision(conn, summary_id, digest)
        output_path = get_summary_output_dir(level) / f"{coverage.period_id}.md"
        if existing is not None and Path(existing.artifact_path).is_file():
            return SummaryBuildResult(Path(existing.artifact_path), existing.revision_id, existing.quality_status, tuple())
        document = synthesize_summary(level=level, period_id=coverage.period_id, evidence=evidence, bundle=bundle, backend=backend or RuntimeBackend())
        groups = [EvidenceGroup(group["evidence_group_id"], group["evidence_kind"], tuple(group["source_refs"]), tuple(group["source_kinds"]), group["payload"]) for group in evidence["evidence_groups"]]
        revision = stage_revision(conn, summary_id=summary_id, input_digest=digest, coverage_start=coverage.period_start,
                                  coverage_end=coverage.coverage_end, closure_status=coverage.closure_status,
                                  document=document, evidence_groups=groups, quality_status=evidence["quality_status"], metadata={"warnings": evidence["warnings"]})
        text = render_summary_markdown(document, revision_id=revision.revision_id, input_digest=digest)
        _write_atomically(output_path, text)
        marked = mark_file_published(conn, revision.revision_id, output_path, full_file_sha256(output_path))
        published = finalize_revision(conn, marked.revision_id)
        return SummaryBuildResult(output_path, published.revision_id, published.quality_status, tuple(evidence["warnings"]))
    finally:
        conn.close()
