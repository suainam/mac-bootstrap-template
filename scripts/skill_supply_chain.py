#!/usr/bin/env python3
"""Govern external/internal Agent Skills supply chain."""

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
DEFAULT_REGISTRY = ROOT / "agent" / "skills-sources.jsonc"
DEFAULT_TARGETS = ROOT / "agent" / "skill-targets.jsonc"
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
        "internal_root": "agent/skills/personal",
        "standalone_internal_root": "agent/skills",
        "quarantine_root": "agent/skills/quarantine",
        "lockfile": ".agent-state/skills-lock.json",
        "run_log_root": ".agent-state/skill-sync-runs",
    }
    merged = {**defaults, **raw}
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
    if raw.get("version") != 1:
        raise RegistryError("skills-sources.jsonc version must be 1")

    paths = _path_map(raw.get("paths", {}))
    defaults = raw.get("defaults", {})
    projects = raw.get("projects", {})
    if not isinstance(projects, dict):
        raise RegistryError("projects must be an object")

    skills: dict[tuple[str, str], SkillRef] = {}
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
        source_defaults = defaults.get(source_type, {})
        source_base = _merge_dict(source_defaults, {k: v for k, v in source_raw.items() if k != "skills"})
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
                base = Path(str(merged.get("path", source_raw.get("path", paths["internal_root"]))))
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
                scope=scope,  # type: ignore[arg-type]
                agents=agents,
                projects=projects_for_skill,
                distribution_state=distribution_state,  # type: ignore[arg-type]
                gate=_gate_policy(merged.get("gate")),
                audit=_audit_policy(merged.get("audit")),
            )

    return Registry(path=path, paths=paths, projects=projects, skills=skills)


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
        if fmt == "flat-md" and strategy != "copy":
            raise RegistryError(f"flat-md target must use copy strategy: {agent}")
        if fmt == "directory" and strategy != "symlink":
            raise RegistryError(f"directory target must use symlink strategy: {agent}")
        raw_path = meta.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise RegistryError(f"target path must be a non-empty string: {agent}")
        targets[agent] = SkillTarget(
            agent=agent,
            path=Path(raw_path),
            format=fmt,  # type: ignore[arg-type]
            strategy=strategy,  # type: ignore[arg-type]
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
    candidates: list[Path] = []
    personal_root = root / registry.paths["internal_root"]
    if personal_root.is_dir():
        for child in personal_root.iterdir():
            if (child / "SKILL.md").is_file():
                candidates.append(child)
    standalone_root = root / registry.paths["standalone_internal_root"]
    if standalone_root.is_dir():
        for child in standalone_root.iterdir():
            if child.name in {"personal", "quarantine"}:
                continue
            if (child / "SKILL.md").is_file():
                candidates.append(child)
    unmanaged = [path for path in candidates if path.resolve() not in managed]
    return sorted(unmanaged)


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


def select_skill(registry: Registry, source_id: str, skill_name: str) -> SkillRef:
    try:
        return registry.skills[(source_id, skill_name)]
    except KeyError as exc:
        raise RegistryError(f"unknown skill: {source_id}/{skill_name}") from exc


def build_skills_sh_fetch_command(skill: SkillRef) -> list[str]:
    if skill.source_type != "external":
        raise RegistryError(f"fetch only supports external skills: {skill.source_id}/{skill.name}")
    if skill.fetcher != "skills.sh":
        raise RegistryError(f"unsupported external fetcher for {skill.source_id}/{skill.name}: {skill.fetcher}")
    if not skill.ref:
        raise RegistryError(f"external skill source missing ref: {skill.source_id}")
    return [
        "npx",
        "skills",
        "add",
        skill.ref,
        "--skill",
        skill.name,
        "--agent",
        "universal",
        "--copy",
        "--yes",
    ]


def _find_fetched_skill_dir(work_dir: Path, skill_name: str) -> Path:
    candidates = [
        work_dir / ".agents" / "skills" / skill_name,
        work_dir / ".claude" / "skills" / skill_name,
        work_dir / ".codex" / "skills" / skill_name,
        work_dir / "skills" / skill_name,
        work_dir / skill_name,
    ]
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file():
            return candidate
    matches = sorted(work_dir.glob(f"**/{skill_name}/SKILL.md"))
    if matches:
        return matches[0].parent
    raise RegistryError(f"skills.sh did not produce {skill_name}/SKILL.md under {work_dir}")


def fetch_external_skill(skill: SkillRef, root: Path = ROOT, dry_run: bool = False) -> CommandResult:
    if skill.quarantine_path is None:
        raise RegistryError(f"external skill missing quarantine path: {skill.source_id}/{skill.name}")
    command = build_skills_sh_fetch_command(skill)
    tmp_work = root / "agent" / "skills" / "quarantine" / ".tmp" / skill.source_id / skill.name / "work"
    destination = root / skill.quarantine_path
    if dry_run:
        print(
            f"DRY-RUN fetch external skill {skill.source_id}/{skill.name} -> {skill.quarantine_path.as_posix()}"
        )
        return CommandResult(
            command=tuple(command),
            cwd=tmp_work,
            destination=destination,
            returncode=0,
            dry_run=True,
        )

    if tmp_work.exists():
        shutil.rmtree(tmp_work)
    tmp_work.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DISABLE_TELEMETRY"] = "1"
    completed = subprocess.run(
        command,
        cwd=tmp_work,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return CommandResult(
            command=tuple(command),
            cwd=tmp_work,
            destination=destination,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    fetched = _find_fetched_skill_dir(tmp_work, skill.name)
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fetched, destination)
    return CommandResult(
        command=tuple(command),
        cwd=tmp_work,
        destination=destination,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def inspect_skill_content(path: Path) -> SkillInspection:
    hasher = hashlib.sha256()
    file_count = 0
    has_scripts = False
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        rel = file_path.relative_to(path)
        if any(part in {".git", "__pycache__"} for part in rel.parts):
            continue
        if rel.parts and rel.parts[0] == "scripts":
            has_scripts = True
        hasher.update(rel.as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(file_path.read_bytes())
        hasher.update(b"\0")
        file_count += 1
    return SkillInspection(
        content_hash="sha256:" + hasher.hexdigest(),
        has_scripts=has_scripts,
        file_count=file_count,
        skill_md_exists=(path / "SKILL.md").is_file(),
    )


def _risk_exceeds(actual: str, maximum: str) -> bool:
    return RISK_ORDER.get(actual.upper(), 99) > RISK_ORDER.get(maximum.upper(), 99)


def evaluate_gate(
    skill: SkillRef,
    inspection: SkillInspection,
    audit: AuditResult | None,
) -> GateDecision:
    reasons: list[str] = []
    if not inspection.skill_md_exists:
        reasons.append("missing SKILL.md")
    if skill.source_type == "external" and inspection.has_scripts and not skill.audit.allow_scripts:
        reasons.append("scripts present but audit.allow_scripts is false")
    if skill.audit.required:
        if audit is None:
            if not skill.audit.allow_unaudited:
                reasons.append("audit required but no audit result is available")
        elif audit.status != "pass":
            reasons.append(f"audit status is {audit.status}")
        elif _risk_exceeds(audit.risk_level, skill.audit.max_risk):
            reasons.append(f"audit risk {audit.risk_level} exceeds max {skill.audit.max_risk}")

    requires_user_approval = bool(skill.gate.manual_approval)
    approved_version_matches = True
    if skill.gate.manual_approval:
        if not skill.gate.approved:
            reasons.append("manual approval required")
            approved_version_matches = False
        elif skill.gate.approved_hash:
            approved_version_matches = skill.gate.approved_hash == inspection.content_hash
            if not approved_version_matches:
                reasons.append("approved hash does not match current content")
        elif skill.source_type == "external":
            approved_version_matches = False
            reasons.append("manual approval for external skill must bind approved_hash")
    return GateDecision(
        allowed=not reasons,
        reasons=tuple(reasons),
        requires_user_approval=requires_user_approval,
        approved_version_matches=approved_version_matches,
    )


def write_run_log(event: dict, root: Path = ROOT) -> Path:
    log_root = root / ".agent-state" / "skill-sync-runs"
    log_root.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H%M%SZ")
    path = log_root / f"{now}.jsonl"
    safe_event = {
        key: value
        for key, value in event.items()
        if key.lower() not in {"env", "environment", "token", "secret", "password"}
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(safe_event, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _summarize(registry: Registry, targets: dict[str, SkillTarget]) -> str:
    external = sum(1 for skill in registry.skills.values() if skill.source_type == "external")
    internal = sum(1 for skill in registry.skills.values() if skill.source_type == "internal")
    global_count = sum(1 for skill in registry.skills.values() if skill.scope == "global")
    project_count = sum(1 for skill in registry.skills.values() if skill.scope == "project")
    return (
        f"skills={len(registry.skills)} external={external} internal={internal} "
        f"global={global_count} project={project_count} targets={len(targets)}"
    )


def expand_target_path(path: Path, root: Path = ROOT) -> Path:
    raw = path.as_posix()
    raw = raw.replace("${BOOTSTRAP}", str(root))
    raw = raw.replace("${HOME}", str(Path.home()))
    return Path(raw).expanduser()


def _skill_source_for_distribution(skill: SkillRef, root: Path) -> Path | None:
    if skill.source_type == "internal" and skill.source_path is not None:
        return root / skill.source_path
    if skill.source_type == "external" and skill.local_shadow_path is not None:
        source = root / skill.local_shadow_path
        if source.exists():
            return source
    if skill.source_type == "external" and skill.quarantine_path is not None:
        source = root / skill.quarantine_path
        if not source.exists():
            return None
        decision = evaluate_gate(skill, inspect_skill_content(source), audit=None)
        if not decision.allowed:
            return None
        return source
    return None


def build_distribution_actions(
    registry: Registry,
    targets: dict[str, SkillTarget],
    root: Path = ROOT,
) -> list[DistributionAction]:
    actions: list[DistributionAction] = []
    for skill in sorted(registry.skills.values(), key=lambda item: (item.source_id, item.name)):
        if skill.distribution_state != "enabled":
            continue
        source = _skill_source_for_distribution(skill, root)
        if source is None:
            continue
        if skill.scope == "project":
            for project_name in skill.projects:
                project = registry.projects[project_name]
                target_path = expand_target_path(Path(project["skills_dir"]), root) / skill.name
                actions.append(
                    DistributionAction(
                        skill_name=skill.name,
                        source=source,
                        target_agent=None,
                        target_path=target_path,
                        action="link-dir",
                    )
                )
            continue
        for agent in skill.agents:
            target = targets[agent]
            base = expand_target_path(target.path, root)
            if target.format == "flat-md":
                actions.append(
                    DistributionAction(
                        skill_name=skill.name,
                        source=source,
                        target_agent=agent,
                        target_path=base / f"{skill.name}.md",
                        action="copy-flat-md",
                    )
                )
            else:
                actions.append(
                    DistributionAction(
                        skill_name=skill.name,
                        source=source,
                        target_agent=agent,
                        target_path=base / skill.name,
                        action="link-dir",
                    )
                )
    return actions


def _is_devspace_worktree(root: Path) -> bool:
    return "/.devspace/worktrees/" in root.as_posix()


def _enabled_distribution_specs(
    registry: Registry,
    targets: dict[str, SkillTarget],
    root: Path = ROOT,
) -> set[tuple[str, str, str]]:
    """Return desired enabled placements as (surface, target_name, skill_name).

    This intentionally does not require an external skill to be fetched or gate-approved.
    Stale cleanup should not remove an enabled external skill just because its quarantine
    copy is not available yet.
    """
    specs: set[tuple[str, str, str]] = set()
    for skill in registry.skills.values():
        if skill.distribution_state != "enabled":
            continue
        if skill.scope == "project":
            for project_name in skill.projects:
                specs.add(("project", project_name, skill.name))
            continue
        for agent in skill.agents:
            if agent in targets:
                specs.add(("global", agent, skill.name))
    return specs


def build_reconcile_actions(
    registry: Registry,
    targets: dict[str, SkillTarget],
    root: Path = ROOT,
) -> list[ReconcileAction]:
    desired = _enabled_distribution_specs(registry, targets, root)
    actions: list[ReconcileAction] = []

    for agent, target in sorted(targets.items()):
        base = expand_target_path(target.path, root)
        if not base.exists():
            continue
        if target.format == "flat-md":
            children = sorted(base.glob("*.md"))
            for child in children:
                skill_name = child.stem
                if ("global", agent, skill_name) in desired:
                    continue
                actions.append(
                    ReconcileAction(
                        surface="global",
                        target_name=agent,
                        skill_name=skill_name,
                        target_path=child,
                        action="remove-flat-md",
                        reason="not enabled for this agent in skills-sources.jsonc",
                    )
                )
            continue
        for child in sorted(base.iterdir()):
            if child.name.startswith("."):
                continue
            if not (child.is_dir() or child.is_symlink()):
                continue
            skill_name = child.name
            if ("global", agent, skill_name) in desired:
                continue
            action = "remove-symlink" if child.is_symlink() else "skip-real-path"
            reason = "not enabled for this agent in skills-sources.jsonc"
            if action == "skip-real-path":
                reason += "; real directory is left untouched"
            actions.append(
                ReconcileAction(
                    surface="global",
                    target_name=agent,
                    skill_name=skill_name,
                    target_path=child,
                    action=action,  # type: ignore[arg-type]
                    reason=reason,
                )
            )

    for project_name, project in sorted(registry.projects.items()):
        base = expand_target_path(Path(project["skills_dir"]), root)
        if not base.exists():
            continue
        for child in sorted(base.iterdir()):
            if child.name.startswith("."):
                continue
            if not (child.is_dir() or child.is_symlink()):
                continue
            skill_name = child.name
            if ("project", project_name, skill_name) in desired:
                continue
            action = "remove-symlink" if child.is_symlink() else "skip-real-path"
            reason = "not enabled for this project in skills-sources.jsonc"
            if action == "skip-real-path":
                reason += "; real directory is left untouched"
            actions.append(
                ReconcileAction(
                    surface="project",
                    target_name=project_name,
                    skill_name=skill_name,
                    target_path=child,
                    action=action,  # type: ignore[arg-type]
                    reason=reason,
                )
            )
    return actions


def apply_reconcile_actions(actions: list[ReconcileAction], *, apply: bool = False) -> None:
    for action in actions:
        prefix = "APPLY" if apply else "DRY-RUN"
        print(
            f"{prefix} {action.action} {action.surface}/{action.target_name}/{action.skill_name} "
            f"{action.target_path} # {action.reason}"
        )
        if not apply:
            continue
        if action.action == "skip-real-path":
            continue
        if action.target_path.is_symlink() or action.target_path.is_file():
            action.target_path.unlink()



def _assert_safe_apply_root(root: Path, *, allow_worktree_apply: bool = False) -> None:
    if _is_devspace_worktree(root) and not allow_worktree_apply:
        raise RegistryError(
            "refusing to apply distribution from a DevSpace worktree; merge to the real checkout "
            "and run from there, or set SKILL_SUPPLY_CHAIN_ALLOW_WORKTREE_APPLY=1 for an explicit override"
        )


def apply_distribution_actions(actions: list[DistributionAction], dry_run: bool = False) -> None:
    for action in actions:
        if dry_run:
            print(f"DRY-RUN {action.action} {action.source} -> {action.target_path}")
            continue
        action.target_path.parent.mkdir(parents=True, exist_ok=True)
        if action.action == "copy-flat-md":
            shutil.copyfile(action.source / "SKILL.md", action.target_path)
            continue
        if action.target_path.is_symlink():
            action.target_path.unlink()
        elif action.target_path.exists():
            backup = action.target_path.with_name(action.target_path.name + ".bak")
            if not backup.exists():
                action.target_path.rename(backup)
            else:
                continue
        action.target_path.symlink_to(action.source)


def _read_frontmatter_line(text: str, key: str) -> str | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    prefix = f"{key}:"
    for line in parts[1].splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return None


def inspect_installed_skill(path: Path) -> dict:
    item: dict[str, object] = {
        "path": str(path),
        "exists": path.exists() or path.is_symlink(),
        "kind": "missing",
        "link_target": None,
        "resolved_path": None,
        "skill_md_exists": False,
        "skill_md_sha256": None,
        "frontmatter_name": None,
        "frontmatter_description": None,
    }
    if not item["exists"]:
        return item
    if path.is_symlink():
        item["kind"] = "symlink"
        item["link_target"] = os.readlink(path)
    elif path.is_dir():
        item["kind"] = "directory"
    elif path.is_file():
        item["kind"] = "file"
    else:
        item["kind"] = "other"
    try:
        item["resolved_path"] = str(path.resolve(strict=True))
    except OSError:
        item["resolved_path"] = None

    skill_md: Path | None = None
    if path.is_file() and path.suffix == ".md":
        skill_md = path
    else:
        candidates = [path / "SKILL.md"]
        try:
            candidates.append(path.resolve(strict=True) / "SKILL.md")
        except OSError:
            pass
        for candidate in candidates:
            if candidate.is_file():
                skill_md = candidate
                break
    if skill_md is not None and skill_md.is_file():
        raw = skill_md.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        item["skill_md_exists"] = True
        item["skill_md_sha256"] = hashlib.sha256(raw).hexdigest()
        item["frontmatter_name"] = _read_frontmatter_line(text, "name")
        description = _read_frontmatter_line(text, "description")
        item["frontmatter_description"] = description[:240] if description else None
    return item


def _snapshot_skill_dir(path: Path, *, flat_md: bool) -> dict[str, dict]:
    if not path.exists():
        return {}
    entries: dict[str, dict] = {}
    if flat_md:
        for child in sorted(path.glob("*.md")):
            entries[child.stem] = inspect_installed_skill(child)
        return entries
    for child in sorted(path.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_dir() or child.is_symlink():
            entries[child.name] = inspect_installed_skill(child)
    return entries


def build_distribution_snapshot(
    registry: Registry,
    targets: dict[str, SkillTarget],
    root: Path = ROOT,
    *,
    label: str = "snapshot",
) -> dict:
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "label": label,
        "created_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose": "Skill distribution snapshot for before/after comparison.",
        "workspace_root": str(root),
        "global_targets": {},
        "project_targets": {},
        "counts": {"global_total_entries": 0, "project_total_entries": 0},
    }
    global_targets = snapshot["global_targets"]
    assert isinstance(global_targets, dict)
    counts = snapshot["counts"]
    assert isinstance(counts, dict)
    for agent, target in sorted(targets.items()):
        base = expand_target_path(target.path, root)
        flat_md = target.format == "flat-md"
        skills = _snapshot_skill_dir(base, flat_md=flat_md)
        global_targets[agent] = {
            "path": str(base),
            "format": target.format,
            "strategy": target.strategy,
            "count": len(skills),
            "skills": skills,
        }
        counts["global_total_entries"] += len(skills)

    project_targets = snapshot["project_targets"]
    assert isinstance(project_targets, dict)
    for project_name, project in sorted(registry.projects.items()):
        base = expand_target_path(Path(project["skills_dir"]), root)
        skills = _snapshot_skill_dir(base, flat_md=False)
        project_targets[project_name] = {
            "path": str(base),
            "format": "directory",
            "count": len(skills),
            "skills": skills,
        }
        counts["project_total_entries"] += len(skills)
    return snapshot


def write_distribution_snapshot(snapshot: dict, root: Path = ROOT, *, label: str) -> Path:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H%M%SZ")
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "snapshot"
    path = root / ".agent-state" / "skill-snapshots" / f"{now}-{safe_label}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _snapshot_surface_names(snapshot: dict, surface: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    surfaces = snapshot.get(surface, {})
    if not isinstance(surfaces, dict):
        return result
    for target_name, target in surfaces.items():
        if not isinstance(target, dict):
            continue
        skills = target.get("skills", {})
        if not isinstance(skills, dict):
            continue
        for skill_name, meta in skills.items():
            result[f"{target_name}/{skill_name}"] = meta if isinstance(meta, dict) else {}
    return result


def compare_distribution_snapshots(before: dict, after: dict) -> dict:
    diff: dict[str, dict[str, list[str]]] = {}
    for surface in ("global_targets", "project_targets"):
        before_items = _snapshot_surface_names(before, surface)
        after_items = _snapshot_surface_names(after, surface)
        before_keys = set(before_items)
        after_keys = set(after_items)
        changed = []
        for key in sorted(before_keys & after_keys):
            if before_items[key].get("skill_md_sha256") != after_items[key].get("skill_md_sha256"):
                changed.append(key)
            elif before_items[key].get("link_target") != after_items[key].get("link_target"):
                changed.append(key)
        diff[surface] = {
            "missing": sorted(before_keys - after_keys),
            "added": sorted(after_keys - before_keys),
            "changed": changed,
        }
    return diff


def cmd_plan(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    targets = load_targets(args.targets)
    print(_summarize(registry, targets))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    targets = load_targets(args.targets)
    errors = validate_registry_sources(registry, ROOT)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"ok skill supply check: {_summarize(registry, targets)}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    if not args.source or not args.skill:
        raise RegistryError("fetch requires --source and --skill")
    skill = select_skill(registry, args.source, args.skill)
    result = fetch_external_skill(skill, ROOT, dry_run=args.dry_run)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode
    if not result.dry_run:
        print(f"fetched external skill {skill.source_id}/{skill.name} -> {skill.quarantine_path}")
    return 0


def _selected_external_skill(args: argparse.Namespace) -> SkillRef:
    registry = load_registry(args.registry)
    if not args.source or not args.skill:
        raise RegistryError(f"{args.command} requires --source and --skill")
    skill = select_skill(registry, args.source, args.skill)
    if skill.source_type != "external":
        raise RegistryError(f"{args.command} only supports external skills: {skill.source_id}/{skill.name}")
    return skill


def cmd_distribute(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    targets = load_targets(args.targets)
    actions = build_distribution_actions(registry, targets, ROOT)
    if not args.dry_run:
        _assert_safe_apply_root(
            ROOT,
            allow_worktree_apply=os.environ.get("SKILL_SUPPLY_CHAIN_ALLOW_WORKTREE_APPLY") == "1",
        )
    apply_distribution_actions(actions, dry_run=args.dry_run)
    if args.dry_run:
        print(f"DRY-RUN distribution actions: {len(actions)}")
    else:
        print(f"applied distribution actions: {len(actions)}")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    targets = load_targets(args.targets)
    actions = build_reconcile_actions(registry, targets, ROOT)
    should_apply = bool(args.apply)
    if should_apply:
        _assert_safe_apply_root(
            ROOT,
            allow_worktree_apply=os.environ.get("SKILL_SUPPLY_CHAIN_ALLOW_WORKTREE_APPLY") == "1",
        )
    apply_reconcile_actions(actions, apply=should_apply)
    skipped = sum(1 for action in actions if action.action == "skip-real-path")
    removable = len(actions) - skipped
    mode = "APPLY" if should_apply else "DRY-RUN"
    print(f"{mode} reconcile actions: total={len(actions)} removable={removable} skipped_real_paths={skipped}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    targets = load_targets(args.targets)
    snapshot = build_distribution_snapshot(registry, targets, ROOT, label=args.label)
    if args.dry_run:
        counts = snapshot["counts"]
        print(
            "DRY-RUN skill snapshot "
            f"label={args.label} global_entries={counts['global_total_entries']} "
            f"project_entries={counts['project_total_entries']}"
        )
        return 0
    path = write_distribution_snapshot(snapshot, ROOT, label=args.label)
    counts = snapshot["counts"]
    print(
        f"wrote skill snapshot {path} "
        f"global_entries={counts['global_total_entries']} "
        f"project_entries={counts['project_total_entries']}"
    )
    return 0


def cmd_snapshot_diff(args: argparse.Namespace) -> int:
    if not args.before or not args.after:
        raise RegistryError("snapshot-diff requires --before and --after")
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    diff = compare_distribution_snapshots(before, after)
    print(json.dumps(diff, ensure_ascii=False, indent=2, sort_keys=True))
    missing = len(diff["global_targets"]["missing"]) + len(diff["project_targets"]["missing"])
    return 1 if missing else 0


def cmd_audit(args: argparse.Namespace) -> int:
    skill = _selected_external_skill(args)
    if args.dry_run:
        print(f"DRY-RUN audit external skill {skill.source_id}/{skill.name}")
        return 0
    inspection = inspect_skill_content(ROOT / skill.quarantine_path) if skill.quarantine_path else None
    decision = evaluate_gate(skill, inspection, audit=None) if inspection else None
    write_run_log(
        {
            "event": "audit",
            "source": skill.source_id,
            "skill": skill.name,
            "result": "pending",
            "reasons": list(decision.reasons) if decision else ["missing quarantine path"],
            "content_hash": inspection.content_hash if inspection else None,
        }
    )
    print(f"audit recorded for {skill.source_id}/{skill.name}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    skill = _selected_external_skill(args)
    if args.dry_run:
        print(f"DRY-RUN diff external skill {skill.source_id}/{skill.name}")
        return 0
    if not skill.quarantine_path:
        raise RegistryError(f"external skill missing quarantine path: {skill.source_id}/{skill.name}")
    inspection = inspect_skill_content(ROOT / skill.quarantine_path)
    print(json.dumps({"source": skill.source_id, "skill": skill.name, "content_hash": inspection.content_hash}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["plan", "fetch", "audit", "diff", "distribute", "reconcile", "snapshot", "snapshot-diff", "check"],
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--source")
    parser.add_argument("--skill")
    parser.add_argument("--label", default="snapshot")
    parser.add_argument("--before")
    parser.add_argument("--after")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true", help="apply destructive reconcile actions")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            return cmd_plan(args)
        if args.command == "fetch":
            return cmd_fetch(args)
        if args.command == "audit":
            return cmd_audit(args)
        if args.command == "diff":
            return cmd_diff(args)
        if args.command == "distribute":
            return cmd_distribute(args)
        if args.command == "reconcile":
            return cmd_reconcile(args)
        if args.command == "snapshot":
            return cmd_snapshot(args)
        if args.command == "snapshot-diff":
            return cmd_snapshot_diff(args)
        if args.command == "check":
            return cmd_check(args)
    except RegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    parser.error(f"unhandled command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
