"""Schema-first synthesis, separated from evidence collection and rendering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from summary_contracts import ContractBundle, EvidenceGroup, SummaryContractError, SummaryDocument, validate_summary_document


CURRENT_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = CURRENT_DIR / "prompts"


class SummarySynthesisError(RuntimeError):
    """Raised after the single contract-repair retry is exhausted."""


def prompt_name_for(level: str) -> str:
    if level == "daily":
        return "daily-summary.md"
    if level == "weekly":
        return "weekly-summary.md"
    if level in {"monthly", "quarterly", "yearly"}:
        return "higher-period-summary.md"
    raise SummarySynthesisError(f"unsupported summary level: {level}")


def render_level_prompt(*, level: str, period_id: str, evidence: Mapping[str, Any], bundle: ContractBundle) -> str:
    template = (PROMPTS_DIR / prompt_name_for(level)).read_text(encoding="utf-8")
    values = {
        "${level}": level,
        "${period}": period_id,
        "${contract_json}": json.dumps(bundle.schema, ensure_ascii=False, sort_keys=True),
        "${taxonomy_json}": json.dumps(bundle.taxonomy, ensure_ascii=False, sort_keys=True),
        "${policy_json}": json.dumps(bundle.policy, ensure_ascii=False, sort_keys=True),
        "${evidence_json}": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
    }
    for marker, replacement in values.items():
        template = template.replace(marker, replacement)
    return template


def _raw_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    raw_text = getattr(response, "raw_text", None)
    if isinstance(raw_text, str):
        return raw_text
    raise SummarySynthesisError("summary backend returned no text")


def _call_backend(backend: Any, prompt: str) -> str:
    try:
        return _raw_text(backend.generate(prompt))
    except TypeError:
        from llm_filter import BackendRequest

        return _raw_text(backend.generate(BackendRequest(prompt=prompt, timeout=backend.timeout)))


def synthesize_summary(
    *,
    level: str,
    period_id: str,
    evidence: Mapping[str, Any],
    bundle: ContractBundle,
    backend: Any,
) -> SummaryDocument:
    """Generate one structured document, retrying once only for contract repair."""

    prompt = render_level_prompt(level=level, period_id=period_id, evidence=evidence, bundle=bundle)
    evidence_group_ids = {str(group["evidence_group_id"]) for group in evidence.get("evidence_groups", [])}
    evidence_groups = {
        str(group["evidence_group_id"]): EvidenceGroup(str(group["evidence_group_id"]), str(group["evidence_kind"]), tuple(group.get("source_refs", [])), tuple(group.get("source_kinds", [])), dict(group.get("payload", {})))
        for group in evidence.get("evidence_groups", [])
    }
    for attempt in range(2):
        raw = _call_backend(backend, prompt)
        try:
            parsed = json.loads(raw)
            validated = validate_summary_document(parsed, bundle, evidence_group_ids=evidence_group_ids, evidence_groups=evidence_groups, lower_item_ids=set(evidence.get("lower_item_ids", [])), enforce_length=True)
            return SummaryDocument.from_dict(validated)
        except (json.JSONDecodeError, SummaryContractError, TypeError) as exc:
            if attempt == 1:
                raise SummarySynthesisError(str(exc)) from exc
            prompt = (
                f"{prompt}\n\nThe previous response failed validation: {exc}. "
                "Return a corrected JSON object only; do not add explanation.\n"
                f"Previous response:\n{raw}"
            )
    raise AssertionError("unreachable")
