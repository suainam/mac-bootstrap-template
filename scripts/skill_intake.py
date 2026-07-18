"""Fetch, inspect, and catalog external skill sources."""

import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

try:
    from scripts import skill_registry as _skill_registry
except ModuleNotFoundError:
    import skill_registry as _skill_registry

globals().update(
    {name: value for name, value in vars(_skill_registry).items() if not name.startswith("__")}
)

RISK_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


@dataclass(frozen=True)
class BundlePromotionResult:
    source_id: str
    destination: Path
    promoted: tuple[str, ...]
    blocked: tuple[str, ...]
    dry_run: bool = False


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
        "skills@latest",
        "add",
        skill.ref,
        "--skill",
        skill.name,
        "--agent",
        "universal",
        "--copy",
        "--yes",
    ]


def build_skills_sh_bundle_fetch_command(bundle: SkillBundle) -> list[str]:
    if bundle.fetcher != "skills.sh":
        raise RegistryError(f"unsupported external bundle fetcher for {bundle.source_id}: {bundle.fetcher}")
    return [
        "npx",
        "skills@latest",
        "add",
        bundle.ref,
        "--all",
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


def fetch_external_skill(
    skill: SkillRef,
    registry: Registry,
    root: Path = ROOT,
    dry_run: bool = False,
) -> CommandResult:
    if skill.quarantine_path is None:
        raise RegistryError(f"external skill missing quarantine path: {skill.source_id}/{skill.name}")
    command = build_skills_sh_fetch_command(skill)
    tmp_work = (
        root
        / registry.paths["quarantine_root"]
        / ".tmp"
        / skill.source_id
        / skill.name
        / "work"
    )
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
    env.setdefault("npm_config_cache", str(tmp_work.parent / "npm-cache"))
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


def _find_fetched_bundle_root(work_dir: Path) -> Path:
    candidates = [
        work_dir / ".agents" / "skills",
        work_dir / ".claude" / "skills",
        work_dir / ".codex" / "skills",
        work_dir / "skills",
    ]
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.rglob("SKILL.md")):
            return candidate
    matches = [
        path
        for path in sorted(work_dir.rglob("SKILL.md"))
        if not any(part in {".git", ".tmp", "__pycache__"} for part in path.relative_to(work_dir).parts)
    ]
    if matches:
        common = Path(os.path.commonpath([str(path.parent) for path in matches]))
        return common
    raise RegistryError(f"skills.sh did not produce a bundle containing SKILL.md under {work_dir}")


def _discover_bundle_catalog_root(bundle_root: Path, source_id: str) -> tuple[BundleCatalogEntry, ...]:
    entries: list[BundleCatalogEntry] = []
    seen_names: set[str] = set()
    for skill_md in sorted(bundle_root.rglob("SKILL.md")):
        relative_md = skill_md.relative_to(bundle_root)
        if any(part in {".git", ".tmp", "__pycache__"} for part in relative_md.parts):
            continue
        skill_dir = skill_md.parent
        name = skill_dir.name
        _validate_name("skill", name)
        if name in seen_names:
            raise RegistryError(f"duplicate bundle skill name: {source_id}/{name}")
        seen_names.add(name)
        entries.append(
            BundleCatalogEntry(
                name=name,
                relative_path=skill_dir.relative_to(bundle_root),
                content_hash=inspect_skill_content(skill_dir).content_hash,
            )
        )
    return tuple(entries)


def write_bundle_catalog(
    bundle: SkillBundle,
    entries: tuple[BundleCatalogEntry, ...],
    root: Path = ROOT,
    output_path: Path | None = None,
) -> Path:
    path = output_path or (root / bundle.catalog_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_id": bundle.source_id,
        "ref": bundle.ref,
        "install_mode": bundle.install_mode,
        "skills": [
            {
                "name": entry.name,
                "relative_path": entry.relative_path.as_posix(),
                "content_hash": entry.content_hash,
            }
            for entry in entries
        ],
    }
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path

def fetch_external_bundle(
    bundle: SkillBundle,
    root: Path = ROOT,
    dry_run: bool = False,
    candidate_root: Path | None = None,
) -> CommandResult:
    command = build_skills_sh_bundle_fetch_command(bundle)
    tmp_work = root / bundle.quarantine_path.parent / ".tmp" / bundle.source_id / "bundle" / "work"
    destination = (candidate_root or root / ".agent-state/skill-candidates") / bundle.source_id
    if dry_run:
        print(f"DRY-RUN fetch external bundle {bundle.source_id} -> {destination.relative_to(root).as_posix()}")
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
    env.setdefault("npm_config_cache", str(tmp_work.parent / "npm-cache"))
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

    fetched_root = _find_fetched_bundle_root(tmp_work)
    entries = _discover_bundle_catalog_root(fetched_root, bundle.source_id)
    if not entries:
        return CommandResult(
            command=tuple(command),
            cwd=tmp_work,
            destination=destination,
            returncode=1,
            stdout=completed.stdout,
            stderr=f"skills.sh returned an empty bundle for {bundle.source_id}",
        )

    candidate = tmp_work.parent / "candidate"
    if candidate.exists():
        shutil.rmtree(candidate)
    shutil.copytree(fetched_root, candidate)
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate.replace(destination)
    write_bundle_catalog(bundle, entries, root, output_path=destination / "catalog.json")
    return CommandResult(
        command=tuple(command),
        cwd=tmp_work,
        destination=destination,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def bundle_needs_fetch(
    registry: Registry,
    bundle: SkillBundle,
    root: Path = ROOT,
) -> bool:
    """Return whether an enabled bundle is absent or lacks registered skills."""
    required = {
        skill.name
        for skill in registry.skills.values()
        if (
            skill.bundle_id == bundle.source_id
            and skill.distribution_state == "enabled"
            and skill.local_shadow_path is None
        )
    }
    entries = load_bundle_catalog(bundle, root)
    if entries is None:
        entries = discover_bundle_catalog(bundle, root)
    available = {
        entry.name
        for entry in entries
        if (root / bundle.quarantine_path / entry.relative_path).is_dir()
    }
    return not required.issubset(available)


def ensure_external_bundles(
    registry: Registry,
    root: Path = ROOT,
    dry_run: bool = False,
) -> tuple[CommandResult, ...]:
    """Fetch enabled bundles only when their registered skills are unavailable."""
    results: list[CommandResult] = []
    for bundle in sorted(registry.bundles.values(), key=lambda item: item.source_id):
        if bundle.distribution_state != "enabled" or not bundle_needs_fetch(registry, bundle, root):
            continue
        result = fetch_external_bundle(
            bundle,
            root,
            dry_run=dry_run,
            candidate_root=root / registry.paths["candidate_root"],
        )
        results.append(result)
        if result.returncode == 0 and not dry_run:
            promote_external_bundle(registry, bundle, root)
    return tuple(results)


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


def discover_bundle_catalog(bundle: SkillBundle, root: Path = ROOT) -> tuple[BundleCatalogEntry, ...]:
    """Discover and hash every Skill directory currently present in a bundle."""
    if not (root / bundle.quarantine_path).is_dir():
        return ()
    return _discover_bundle_catalog_root(root / bundle.quarantine_path, bundle.source_id)


def candidate_bundle_path(registry: Registry, bundle: SkillBundle, root: Path = ROOT) -> Path:
    return root / registry.paths["candidate_root"] / bundle.source_id


def load_bundle_catalog_path(
    bundle: SkillBundle,
    path: Path,
) -> tuple[BundleCatalogEntry, ...] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"invalid bundle catalog: {path}") from exc
    if raw.get("source_id") != bundle.source_id or raw.get("ref") != bundle.ref:
        raise RegistryError(f"bundle catalog identity mismatch: {bundle.source_id}")
    raw_skills = raw.get("skills")
    if not isinstance(raw_skills, list):
        raise RegistryError(f"bundle catalog skills must be a list: {bundle.source_id}")
    entries: list[BundleCatalogEntry] = []
    seen_names: set[str] = set()
    for item in raw_skills:
        if not isinstance(item, dict):
            raise RegistryError(f"invalid bundle catalog entry: {bundle.source_id}")
        name = item.get("name")
        relative_path = item.get("relative_path")
        content_hash = item.get("content_hash")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise RegistryError(f"invalid bundle catalog skill name: {bundle.source_id}")
        relative = Path(str(relative_path)) if isinstance(relative_path, str) else None
        if relative is None or relative.is_absolute() or ".." in relative.parts:
            raise RegistryError(f"invalid bundle catalog path: {bundle.source_id}/{name}")
        if not isinstance(content_hash, str) or not content_hash.startswith("sha256:"):
            raise RegistryError(f"invalid bundle catalog hash: {bundle.source_id}/{name}")
        if name in seen_names:
            raise RegistryError(f"duplicate bundle catalog skill: {bundle.source_id}/{name}")
        seen_names.add(name)
        entries.append(BundleCatalogEntry(name, relative, content_hash))
    return tuple(entries)


def load_bundle_catalog(bundle: SkillBundle, root: Path = ROOT) -> tuple[BundleCatalogEntry, ...] | None:
    return load_bundle_catalog_path(bundle, root / bundle.catalog_path)


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
                auto_safe = (
                    skill.source_type == "external"
                    and skill.gate.auto_update
                    and skill.gate.approved
                    and not inspection.has_scripts
                    and skill.audit.max_risk.upper() == "LOW"
                )
                if auto_safe:
                    approved_version_matches = True
                else:
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


def promote_external_bundle(
    registry: Registry,
    bundle: SkillBundle,
    root: Path = ROOT,
    dry_run: bool = False,
) -> BundlePromotionResult:
    """Promote only policy-approved candidate skills into active quarantine."""
    candidate_root = candidate_bundle_path(registry, bundle, root)
    candidate_catalog = load_bundle_catalog_path(bundle, candidate_root / "catalog.json")
    if candidate_catalog is None:
        raise RegistryError(f"bundle candidate is unavailable: {bundle.source_id}")

    active_root = root / bundle.quarantine_path
    promote_root = active_root.parent / f".{bundle.source_id}.promote"
    if promote_root.exists():
        shutil.rmtree(promote_root)
    if active_root.is_dir() and not active_root.is_symlink():
        shutil.copytree(active_root, promote_root)
    else:
        promote_root.mkdir(parents=True, exist_ok=True)

    promoted: list[str] = []
    blocked: list[str] = []
    registered = {
        skill.name: skill
        for skill in registry.skills.values()
        if skill.bundle_id == bundle.source_id
    }
    for entry in candidate_catalog:
        skill = registered.get(entry.name)
        if skill is None:
            blocked.append(f"{entry.name}:unregistered")
            continue
        source = candidate_root / entry.relative_path
        if not source.is_dir():
            blocked.append(f"{entry.name}:missing")
            continue
        inspection = inspect_skill_content(source)
        decision = evaluate_gate(skill, inspection, audit=None)
        current = active_root / entry.relative_path
        auto_update = (
            current.is_dir()
            and skill.gate.auto_update
            and skill.gate.approved
            and not inspection.has_scripts
            and skill.audit.max_risk.upper() == "LOW"
        )
        if not decision.allowed or (not auto_update and skill.gate.approved_hash != inspection.content_hash):
            blocked.append(f"{entry.name}:{','.join(decision.reasons) or 'approval-baseline-mismatch'}")
            continue
        target = promote_root / entry.relative_path
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        promoted.append(entry.name)

    result = BundlePromotionResult(
        source_id=bundle.source_id,
        destination=active_root,
        promoted=tuple(sorted(promoted)),
        blocked=tuple(sorted(blocked)),
        dry_run=dry_run,
    )
    if dry_run:
        shutil.rmtree(promote_root)
        return result

    if not promoted and not active_root.exists():
        shutil.rmtree(promote_root)
        return result
    active_backup = active_root.parent / f".{bundle.source_id}.previous"
    if active_backup.exists():
        shutil.rmtree(active_backup)
    if active_root.exists():
        active_root.replace(active_backup)
    promote_root.replace(active_root)
    if active_backup.exists():
        shutil.rmtree(active_backup)
    entries = _discover_bundle_catalog_root(active_root, bundle.source_id)
    write_bundle_catalog(bundle, entries, root)
    write_run_log(
        {
            "event": "bundle-promote",
            "source": bundle.source_id,
            "promoted": list(result.promoted),
            "blocked": list(result.blocked),
        },
        registry,
        root,
    )
    return result


def update_external_bundles(
    registry: Registry,
    root: Path = ROOT,
    source_id: str | None = None,
    dry_run: bool = False,
) -> tuple[tuple[CommandResult, ...], tuple[BundlePromotionResult, ...]]:
    """Fetch enabled external bundles, then promote only safe candidates."""
    bundles = sorted(registry.bundles.values(), key=lambda item: item.source_id)
    if source_id is not None:
        bundles = [bundle for bundle in bundles if bundle.source_id == source_id]
    fetches: list[CommandResult] = []
    promotions: list[BundlePromotionResult] = []
    for bundle in bundles:
        if bundle.distribution_state != "enabled":
            continue
        result = fetch_external_bundle(
            bundle,
            root,
            dry_run=dry_run,
            candidate_root=root / registry.paths["candidate_root"],
        )
        fetches.append(result)
        if result.returncode == 0:
            if dry_run:
                print(f"DRY-RUN promote external bundle {bundle.source_id}")
            else:
                promotions.append(promote_external_bundle(registry, bundle, root))
    return tuple(fetches), tuple(promotions)


def write_run_log(event: dict, registry: Registry, root: Path = ROOT) -> Path:
    log_root = root / registry.paths["run_log_root"]
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
