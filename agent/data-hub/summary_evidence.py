"""Collect deterministic, cited evidence for the structured summary engine."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Mapping

from summary_contracts import canonical_json


SUMMARY_SOURCE_PREFIX = "70_Summaries/"


def _is_primary_source(ref: str) -> bool:
    return bool(ref) and not ref.replace("\\", "/").startswith(SUMMARY_SOURCE_PREFIX)


def _stable_group_id(evidence_kind: str, source_refs: list[str], payload: Mapping[str, Any]) -> str:
    value = canonical_json(
        {
            "evidence_kind": evidence_kind,
            "source_refs": sorted(source_refs),
            "payload": payload,
        }
    )
    return "evg_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _group(evidence_kind: str, source_kind: str, ref: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    if not _is_primary_source(ref):
        return None
    normalized_payload = deepcopy(dict(payload))
    return {
        "evidence_group_id": _stable_group_id(evidence_kind, [ref], normalized_payload),
        "evidence_kind": evidence_kind,
        "source_refs": [ref],
        "source_kinds": [source_kind],
        "payload": normalized_payload,
    }


def _citation_path(citation: Mapping[str, Any]) -> str:
    return str(citation.get("path") or citation.get("source_ref") or citation.get("file") or "")


def _deep_research(client: Any, message: str) -> tuple[dict[str, Any], list[str]]:
    if client is None:
        return {}, ["llm_wiki deep research unavailable"]
    try:
        return dict(client.chat(message, mode="deep")), []
    except Exception as exc:  # noqa: BLE001 - optional external evidence must degrade safely.
        return {}, [f"llm_wiki deep research unavailable: {type(exc).__name__}: {exc}"]


def collect_summary_evidence(
    *,
    level: str,
    period: str,
    query: str,
    retrieval_packet: Mapping[str, Any],
    llm_wiki_client: Any | None,
) -> dict[str, Any]:
    """Return a deterministic primary-source packet; llm_wiki only enriches it."""

    groups: list[dict[str, Any]] = []
    local_markdown = retrieval_packet.get("local_markdown", {})
    for bucket, source_kind in (("daily", "daily_note"), ("adrs", "adr"), ("cards", "card")):
        for hit in local_markdown.get(bucket, []):
            ref = str(hit.get("path", ""))
            group = _group("local_markdown", source_kind, ref, hit)
            if group:
                groups.append(group)
    for loop in retrieval_packet.get("open_loops", []):
        ref = str(loop.get("candidate_id", ""))
        group = _group("open_loop", "knowledge_candidate", ref, loop)
        if group:
            groups.append(group)

    prompt = f"For {level} summary period {period}, find cited, reusable evidence for: {query}"
    deep_research, warnings = _deep_research(llm_wiki_client, prompt)
    for citation in deep_research.get("citations", []):
        if not isinstance(citation, Mapping):
            continue
        ref = _citation_path(citation)
        group = _group("llm_wiki_citation", "llm_wiki", ref, citation)
        if group:
            groups.append(group)

    groups.sort(key=lambda group: group["evidence_group_id"])
    deduped = {group["evidence_group_id"]: group for group in groups}
    evidence_groups = [deduped[group_id] for group_id in sorted(deduped)]
    return {
        "level": level,
        "period": period,
        "query": query,
        "evidence_groups": evidence_groups,
        "deep_research": deep_research,
        "quality_status": "complete" if not warnings else "degraded",
        "warnings": warnings,
    }
