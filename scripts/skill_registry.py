#!/usr/bin/env python3
"""Registry models and JSONC loading for the skill supply chain."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "agent-skills" / "registry" / "sources.jsonc"
DEFAULT_TARGETS = ROOT / "agent-skills" / "registry" / "targets.jsonc"
VALID_AGENTS = {
    "claude",
    "codex",
    "opencode",
    "pi",
    "reasonix",
    "antigravity",
    "cross-agent",
}
VALID_SCOPES = {"global", "project"}
VALID_SOURCE_TYPES = {"internal", "external"}
VALID_TARGET_FORMATS = {"directory", "flat-md"}
VALID_TARGET_STRATEGIES = {"symlink", "copy"}
VALID_DISTRIBUTION_STATES = {"enabled", "staged", "disabled", "merged"}
VALID_BUNDLE_INSTALL_MODES = {"all"}
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class AuditPolicy:
    required: bool = False
    allow_unaudited: bool = False
    max_risk: str = "LOW"
    allow_scripts: bool = False
    local_validate: bool = True


@dataclass(frozen=True)
class GatePolicy:
    manual_approval: bool = False
    approved: bool = False
    approved_by: str | None = None
    approved_at: str | None = None
    approved_version: str | None = None
    approved_hash: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class SkillRef:
    source_id: str
    name: str
    source_type: Literal["internal", "external"]
    fetcher: str | None
    ref: str | None
    source_path: Path | None
    quarantine_path: Path | None
    local_shadow_path: Path | None
    bundle_id: str | None
    scope: Literal["global", "project"]
    agents: tuple[str, ...]
    projects: tuple[str, ...]
    distribution_state: Literal["enabled", "staged", "disabled", "merged"]
    gate: GatePolicy
    audit: AuditPolicy


@dataclass(frozen=True)
class SkillTarget:
    agent: str
    path: Path
    format: Literal["directory", "flat-md"]
    strategy: Literal["symlink", "copy"]
    legacy_formats: tuple[Literal["directory", "flat-md"], ...] = ()


@dataclass(frozen=True)
class SkillBundle:
    source_id: str
    fetcher: str
    ref: str
    install_mode: Literal["all"]
    distribution_state: Literal["enabled", "staged", "disabled", "merged"]
    catalog_path: Path
    quarantine_path: Path


@dataclass(frozen=True)
class BundleCatalogEntry:
    name: str
    relative_path: Path
    content_hash: str


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    cwd: Path
    destination: Path
    returncode: int
    stdout: str = ""
    stderr: str = ""
    dry_run: bool = False


@dataclass(frozen=True)
class DistributionAction:
    skill_name: str
    source: Path
    target_agent: str | None
    target_path: Path
    action: Literal["link-dir", "copy-flat-md"]


@dataclass(frozen=True)
class ReconcileAction:
    surface: str
    target_name: str
    skill_name: str
    target_path: Path
    action: Literal["remove-symlink", "remove-flat-md", "skip-real-path"]
    reason: str


@dataclass(frozen=True)
class SkillInspection:
    content_hash: str
    has_scripts: bool
    file_count: int
    skill_md_exists: bool


@dataclass(frozen=True)
class AuditResult:
    status: Literal["pass", "warn", "fail", "missing"]
    risk_level: str
    source: str
    raw: dict


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reasons: tuple[str, ...]
    requires_user_approval: bool
    approved_version_matches: bool


@dataclass(frozen=True)
class Registry:
    path: Path
    paths: dict[str, Path]
    projects: dict[str, dict]
    skills: dict[tuple[str, str], SkillRef]
    bundles: dict[str, SkillBundle]


class RegistryError(ValueError):
    """Raised when a skill registry file is invalid."""


def strip_jsonc_comments(text: str) -> str:
    """Strip // and /* */ comments while preserving quoted strings."""
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i = min(i + 2, len(text))
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def load_jsonc(path: Path) -> dict:
    return json.loads(strip_jsonc_comments(path.read_text(encoding="utf-8")))


def _merge_dict(base: dict | None, override: dict | None) -> dict:
    merged = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _audit_policy(raw: dict | None) -> AuditPolicy:
    raw = raw or {}
    return AuditPolicy(
        required=bool(raw.get("required", False)),
        allow_unaudited=bool(raw.get("allow_unaudited", False)),
        max_risk=str(raw.get("max_risk", "LOW")),
        allow_scripts=bool(raw.get("allow_scripts", False)),
        local_validate=bool(raw.get("local_validate", True)),
    )


def _gate_policy(raw: dict | None) -> GatePolicy:
    raw = raw or {}
    return GatePolicy(
        manual_approval=bool(raw.get("manual_approval", False)),
        approved=bool(raw.get("approved", False)),
        approved_by=raw.get("approved_by"),
        approved_at=raw.get("approved_at"),
        approved_version=raw.get("approved_version"),
        approved_hash=raw.get("approved_hash"),
        reason=raw.get("reason"),
    )


def _path_map(raw: dict) -> dict[str, Path]:
    defaults = {
        "local_root": "agent-skills/local",
        "quarantine_root": "agent-skills/external/quarantine",
        "lockfile": ".agent-state/skills-lock.json",
        "run_log_root": ".agent-state/skill-sync-runs",
        "snapshot_root": ".agent-state/skill-snapshots",
    }
    merged = {**defaults, **raw}
    unknown = sorted(set(merged) - set(defaults))
    if unknown:
        raise RegistryError(f"unsupported registry path keys: {', '.join(unknown)}")
    return {key: Path(value) for key, value in merged.items()}


def _tuple_of_strings(raw: object, *, name: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise RegistryError(f"{name} must be an array of strings")
    return tuple(raw)


def _validate_name(kind: str, name: str) -> None:
    if not NAME_RE.match(name):
        raise RegistryError(f"invalid {kind} name: {name}")


def load_registry(path: Path = DEFAULT_REGISTRY) -> Registry:
    raw = load_jsonc(path)
    if raw.get("version") != 2:
        raise RegistryError("sources.jsonc version must be 2")

    paths = _path_map(raw.get("paths", {}))
    defaults = raw.get("defaults", {})
    projects = raw.get("projects", {})
    if not isinstance(projects, dict):
        raise RegistryError("projects must be an object")

    skills: dict[tuple[str, str], SkillRef] = {}
    bundles: dict[str, SkillBundle] = {}
    sources = raw.get("sources", {})
    if not isinstance(sources, dict) or not sources:
        raise RegistryError("sources must be a non-empty object")

    for source_id, source_raw in sorted(sources.items()):
        _validate_name("source", source_id)
        if not isinstance(source_raw, dict):
            raise RegistryError(f"source must be an object: {source_id}")
        source_type = source_raw.get("type")
        if source_type not in VALID_SOURCE_TYPES:
            raise RegistryError(f"invalid source type for {source_id}: {source_type}")
        bundle_raw = source_raw.get("bundle")
        bundle_id: str | None = None
        if bundle_raw is not None:
            if source_type != "external":
                raise RegistryError(f"only external sources can define bundles: {source_id}")
            if not isinstance(bundle_raw, dict):
                raise RegistryError(f"bundle must be an object: {source_id}")
            install_mode = bundle_raw.get("install_mode")
            if install_mode not in VALID_BUNDLE_INSTALL_MODES:
                raise RegistryError(f"invalid bundle install_mode for {source_id}: {install_mode}")
            bundle_state = str(bundle_raw.get("distribution_state", "enabled"))
            if bundle_state not in VALID_DISTRIBUTION_STATES:
                raise RegistryError(
                    f"invalid bundle distribution_state for {source_id}: {bundle_state}"
                )
            catalog_raw = bundle_raw.get("catalog_path")
            if not isinstance(catalog_raw, str) or not catalog_raw:
                raise RegistryError(f"bundle catalog_path must be a non-empty string: {source_id}")
            fetcher = source_raw.get("fetcher")
            ref = source_raw.get("ref")
            if not isinstance(fetcher, str) or not fetcher:
                raise RegistryError(f"bundle source missing fetcher: {source_id}")
            if not isinstance(ref, str) or not ref:
                raise RegistryError(f"bundle source missing ref: {source_id}")
            bundle_id = source_id
            bundles[source_id] = SkillBundle(
                source_id=source_id,
                fetcher=fetcher,
                ref=ref,
                install_mode=install_mode,  # type: ignore[arg-type]
                distribution_state=bundle_state,  # type: ignore[arg-type]
                catalog_path=Path(catalog_raw),
                quarantine_path=paths["quarantine_root"] / source_id,
            )
        source_defaults = defaults.get(source_type, {})
        source_base = _merge_dict(
            source_defaults,
            {k: v for k, v in source_raw.items() if k not in {"skills", "bundle"}},
        )
        source_skills = source_raw.get("skills", {})
        if not isinstance(source_skills, dict) or not source_skills:
            raise RegistryError(f"source needs non-empty skills object: {source_id}")

        for skill_name, skill_raw in sorted(source_skills.items()):
            _validate_name("skill", skill_name)
            merged = _merge_dict(source_base, skill_raw or {})
            scope = merged.get("scope")
            if scope not in VALID_SCOPES:
                raise RegistryError(f"invalid scope for {source_id}/{skill_name}: {scope}")
            agents = _tuple_of_strings(merged.get("agents"), name=f"{source_id}/{skill_name}.agents")
            unknown_agents = sorted(set(agents) - VALID_AGENTS)
            if unknown_agents:
                raise RegistryError(f"invalid agents for {source_id}/{skill_name}: {unknown_agents}")
            projects_for_skill = _tuple_of_strings(
                merged.get("projects"), name=f"{source_id}/{skill_name}.projects"
            )
            unknown_projects = sorted(set(projects_for_skill) - set(projects))
            if unknown_projects:
                raise RegistryError(f"unknown projects for {source_id}/{skill_name}: {unknown_projects}")
            if scope == "project" and not projects_for_skill:
                raise RegistryError(f"project skill needs projects: {source_id}/{skill_name}")
            distribution_state = str(merged.get("distribution_state", "enabled"))
            if distribution_state not in VALID_DISTRIBUTION_STATES:
                raise RegistryError(
                    f"invalid distribution_state for {source_id}/{skill_name}: {distribution_state}"
                )

            local_shadow_raw = merged.get("local_shadow_path")
            local_shadow_path = Path(local_shadow_raw) if isinstance(local_shadow_raw, str) else None

            if source_type == "external":
                source_path = None
                quarantine_path = paths["quarantine_root"] / source_id / skill_name
            else:
                base = Path(str(merged.get("path", source_raw.get("path", paths["local_root"]))))
                source_path = base / skill_name
                quarantine_path = None

            key = (source_id, skill_name)
            if key in skills:
                raise RegistryError(f"duplicate skill key: {source_id}/{skill_name}")
            skills[key] = SkillRef(
                source_id=source_id,
                name=skill_name,
                source_type=source_type,  # type: ignore[arg-type]
                fetcher=merged.get("fetcher"),
                ref=merged.get("ref"),
                source_path=source_path,
                quarantine_path=quarantine_path,
                local_shadow_path=local_shadow_path,
                bundle_id=bundle_id,
                scope=scope,  # type: ignore[arg-type]
                agents=agents,
                projects=projects_for_skill,
                distribution_state=distribution_state,  # type: ignore[arg-type]
                gate=_gate_policy(merged.get("gate")),
                audit=_audit_policy(merged.get("audit")),
            )

    return Registry(path=path, paths=paths, projects=projects, skills=skills, bundles=bundles)


def load_targets(path: Path = DEFAULT_TARGETS) -> dict[str, SkillTarget]:
    raw = load_jsonc(path)
    if raw.get("version") != 1:
        raise RegistryError("skill-targets.jsonc version must be 1")
    targets_raw = raw.get("targets", {})
    if not isinstance(targets_raw, dict) or not targets_raw:
        raise RegistryError("targets must be a non-empty object")

    targets: dict[str, SkillTarget] = {}
    for agent, meta in sorted(targets_raw.items()):
        if agent not in VALID_AGENTS:
            raise RegistryError(f"invalid target agent: {agent}")
        if not isinstance(meta, dict):
            raise RegistryError(f"target must be an object: {agent}")
        fmt = meta.get("format")
        strategy = meta.get("strategy")
        if fmt not in VALID_TARGET_FORMATS:
            raise RegistryError(f"invalid target format for {agent}: {fmt}")
        if strategy not in VALID_TARGET_STRATEGIES:
            raise RegistryError(f"invalid target strategy for {agent}: {strategy}")
        if fmt != "directory" or strategy != "symlink":
            raise RegistryError(f"active target must use directory/symlink strategy: {agent}")
        legacy_formats_raw = meta.get("legacy_formats", [])
        if not isinstance(legacy_formats_raw, list) or any(
            legacy_format not in VALID_TARGET_FORMATS for legacy_format in legacy_formats_raw
        ):
            raise RegistryError(f"invalid legacy_formats for {agent}")
        if fmt in legacy_formats_raw:
            raise RegistryError(f"target format cannot also be legacy for {agent}: {fmt}")
        raw_path = meta.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise RegistryError(f"target path must be a non-empty string: {agent}")
        targets[agent] = SkillTarget(
            agent=agent,
            path=Path(raw_path),
            format=fmt,  # type: ignore[arg-type]
            strategy=strategy,  # type: ignore[arg-type]
            legacy_formats=tuple(legacy_formats_raw),  # type: ignore[arg-type]
        )
    return targets


def _parse_skill_frontmatter(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    lines = text.splitlines()
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or line.startswith(" "):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


def validate_skill_dir(path: Path, expected_name: str) -> list[str]:
    errors: list[str] = []
    skill_md = path / "SKILL.md"
    if not skill_md.is_file():
        return [f"missing SKILL.md: {path}"]
    meta = _parse_skill_frontmatter(skill_md)
    actual_name = meta.get("name")
    if not actual_name:
        errors.append(f"missing frontmatter name: {skill_md}")
    elif actual_name != expected_name:
        errors.append(f"frontmatter name mismatch: {skill_md} expected={expected_name} actual={actual_name}")
    if "description" not in meta:
        errors.append(f"missing frontmatter description: {skill_md}")
    return errors


def _managed_local_skill_source_paths(registry: Registry, root: Path) -> set[Path]:
    paths: set[Path] = set()
    for skill in registry.skills.values():
        if skill.source_type == "internal" and skill.source_path is not None:
            paths.add((root / skill.source_path).resolve())
        if skill.local_shadow_path is not None:
            paths.add((root / skill.local_shadow_path).resolve())
    return paths


def find_unmanaged_skill_dirs(registry: Registry, root: Path = ROOT) -> list[Path]:
    managed = _managed_local_skill_source_paths(registry, root)
    local_root = root / registry.paths["local_root"]
    if not local_root.is_dir():
        return []
    candidates = {
        skill_md.parent.resolve()
        for skill_md in local_root.rglob("SKILL.md")
        if skill_md.is_file()
    }
    return sorted(path for path in candidates if path not in managed)


def validate_registry_sources(registry: Registry, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for skill in registry.skills.values():
        if skill.source_type != "internal" or skill.source_path is None:
            continue
        errors.extend(validate_skill_dir(root / skill.source_path, skill.name))
    for path in find_unmanaged_skill_dirs(registry, root):
        errors.append(f"unmanaged internal skill source: {path.relative_to(root)}")
    return errors


RISK_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
