"""Versioned contracts for structured Daily-to-Yearly summaries."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


CURRENT_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = CURRENT_DIR / "prompts"


class SummaryContractError(ValueError):
    """Raised when a summary or its contract assets violate the public contract."""


@dataclass(frozen=True)
class EvidenceGroup:
    evidence_group_id: str
    evidence_kind: str
    source_refs: tuple[str, ...]
    source_kinds: tuple[str, ...]
    payload: dict[str, Any]


@dataclass(frozen=True)
class ContractBundle:
    schema: dict[str, Any]
    taxonomy: dict[str, Any]
    policy: dict[str, Any]
    hashes: dict[str, str]


@dataclass(frozen=True)
class SummaryDocument:
    contract_version: str
    taxonomy_version: str
    policy_version: str
    level: str
    period: str
    headline: str
    items: tuple[dict[str, Any], ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SummaryDocument":
        return cls(
            contract_version=str(value["contract_version"]),
            taxonomy_version=str(value["taxonomy_version"]),
            policy_version=str(value["policy_version"]),
            level=str(value["level"]),
            period=str(value["period"]),
            headline=str(value["headline"]),
            items=tuple(deepcopy(value["items"])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "taxonomy_version": self.taxonomy_version,
            "policy_version": self.policy_version,
            "level": self.level,
            "period": self.period,
            "headline": self.headline,
            "items": deepcopy(list(self.items)),
        }


def canonical_json(value: Any) -> str:
    """Return stable UTF-8 JSON for hashing and persistence."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SummaryContractError(f"cannot load contract asset {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise SummaryContractError(f"contract asset must be an object: {path.name}")
    return value


def load_contract_bundle(prompts_dir: Path | None = None) -> ContractBundle:
    """Load and cross-check the public schema, taxonomy, and policy assets."""

    directory = prompts_dir or PROMPTS_DIR
    assets = {
        "schema": _load_json(directory / "summary-output.schema.json"),
        "taxonomy": _load_json(directory / "summary-dimensions.v1.json"),
        "policy": _load_json(directory / "summary-policy.v1.json"),
    }
    schema = assets["schema"]
    taxonomy = assets["taxonomy"]
    policy = assets["policy"]

    versions = {
        schema.get("contract_version"),
        taxonomy.get("contract_version"),
        policy.get("contract_version"),
    }
    if versions != {"summary-v1"}:
        raise SummaryContractError("contract_version mismatch across contract assets")
    if schema.get("taxonomy_version") != taxonomy.get("version"):
        raise SummaryContractError("taxonomy_version mismatch across contract assets")
    if schema.get("policy_version") != policy.get("version"):
        raise SummaryContractError("policy_version mismatch across contract assets")

    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise SummaryContractError(f"invalid summary JSON schema: {exc}") from exc

    hashes = {name: _sha256_text(canonical_json(value)) for name, value in assets.items()}
    return ContractBundle(schema=schema, taxonomy=taxonomy, policy=policy, hashes=hashes)


def _format_validation_error(error: Any) -> str:
    path = ".".join(str(part) for part in error.absolute_path)
    return f"{path}: {error.message}" if path else error.message


def _reject_placeholders(value: Mapping[str, Any]) -> None:
    exact_placeholders = {"待归纳", "暂无建议", "继续推进"}
    for index, item in enumerate(value.get("items", [])):
        for field in ("title", "conclusion", "value", "trend", "period_change"):
            text = str(item.get(field, "")).strip()
            if text in exact_placeholders or "待 llm_filter" in text:
                raise SummaryContractError(f"placeholder content at items.{index}.{field}")


def validate_summary_document(
    value: dict[str, Any],
    bundle: ContractBundle,
    *,
    evidence_group_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Validate schema, taxonomy, insight count, evidence references, and value rules."""

    errors = sorted(
        Draft202012Validator(bundle.schema).iter_errors(value),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        raise SummaryContractError("; ".join(_format_validation_error(error) for error in errors))

    expected_versions = {
        "contract_version": bundle.schema["contract_version"],
        "taxonomy_version": bundle.taxonomy["version"],
        "policy_version": bundle.policy["version"],
    }
    for field, expected in expected_versions.items():
        if value[field] != expected:
            raise SummaryContractError(f"{field} must be {expected}")

    allowed_dimensions = {entry["key"] for entry in bundle.taxonomy["dimensions"]}
    max_dimensions = int(bundle.policy["max_dimensions_per_item"])
    for index, item in enumerate(value["items"]):
        dimensions = item["dimensions"]
        if len(dimensions) > max_dimensions or len(dimensions) != len(set(dimensions)):
            raise SummaryContractError(f"dimensions invalid at items.{index}")
        unknown = set(dimensions) - allowed_dimensions
        if unknown:
            raise SummaryContractError(f"dimensions unknown at items.{index}: {sorted(unknown)}")
        if evidence_group_ids is not None:
            unknown_groups = set(item["evidence_group_ids"]) - evidence_group_ids
            if unknown_groups:
                raise SummaryContractError(
                    f"evidence_group_ids unknown at items.{index}: {sorted(unknown_groups)}"
                )

    if value["level"] == "daily":
        insight_count = sum(item["item_type"] == "insight" for item in value["items"])
        allowed_counts = set(bundle.policy["daily_insights"]["allowed"])
        if insight_count not in allowed_counts:
            raise SummaryContractError(
                f"insight count must be one of {sorted(allowed_counts)}, got {insight_count}"
            )

    _reject_placeholders(value)
    return deepcopy(value)


def build_input_digest(
    *,
    level: str,
    period: str,
    evidence_packet: Mapping[str, Any],
    bundle: ContractBundle,
    prompt: str,
    backend_kind: str,
    model: str,
) -> str:
    """Build the deterministic digest that identifies an immutable summary revision."""

    digest_input = {
        "level": level,
        "period": period,
        "evidence_packet": evidence_packet,
        "prompt_hash": _sha256_text(prompt),
        "contract_hashes": bundle.hashes,
        "backend_kind": backend_kind,
        "model": model,
    }
    return hashlib.sha256(canonical_json(digest_input).encode("utf-8")).hexdigest()
