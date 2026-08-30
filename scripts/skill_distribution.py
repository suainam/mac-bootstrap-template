"""Resolve and reconcile skill distribution targets."""

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

try:
    from scripts import skill_registry as _skill_registry
except ModuleNotFoundError:
    import skill_registry as _skill_registry

globals().update(
    {name: value for name, value in vars(_skill_registry).items() if not name.startswith("__")}
)

try:
    from scripts import skill_intake as _skill_intake
except ModuleNotFoundError:
    import skill_intake as _skill_intake

globals().update(
    {name: value for name, value in vars(_skill_intake).items() if not name.startswith("__")}
)

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


def _project_targets(
    registry: Registry,
    project_name: str,
    root: Path,
) -> tuple[tuple[str, Path], ...]:
    project = registry.projects[project_name]
    return tuple(
        (target_name, expand_target_path(path, root))
        for target_name, path in project_skill_dirs(project_name, project)
    )


def _bundle_skill_source(registry: Registry, skill: SkillRef, root: Path) -> Path | None:
    if skill.bundle_id is None:
        return None
    bundle = registry.bundles.get(skill.bundle_id)
    if bundle is None:
        return None
    entries = load_bundle_catalog(bundle, root)
    if entries is None:
        entries = discover_bundle_catalog(bundle, root)
    for entry in entries:
        if entry.name == skill.name:
            source = root / bundle.quarantine_path / entry.relative_path
            return source if source.is_dir() else None
    return None


def _skill_source_path(registry: Registry, skill: SkillRef, root: Path) -> Path | None:
    if skill.source_type == "internal" and skill.source_path is not None:
        return root / skill.source_path
    if skill.source_type == "external" and skill.local_shadow_path is not None:
        source = root / skill.local_shadow_path
        if source.exists():
            return source
    if skill.source_type == "external" and skill.quarantine_path is not None:
        source = _bundle_skill_source(registry, skill, root) or (root / skill.quarantine_path)
        return source
    return None


def _skill_source_for_distribution(registry: Registry, skill: SkillRef, root: Path) -> Path | None:
    source = _skill_source_path(registry, skill, root)
    if source is None or not source.exists():
        return None
    if skill.source_type == "external" and skill.local_shadow_path is None:
        decision = evaluate_gate(skill, inspect_skill_content(source), audit=None)
        if not decision.allowed:
            return None
    return source


def _skill_distribution_enabled(registry: Registry, skill: SkillRef) -> bool:
    if skill.distribution_state != "enabled":
        return False
    if skill.bundle_id is None:
        return True
    bundle = registry.bundles.get(skill.bundle_id)
    return bundle is not None and bundle.distribution_state == "enabled"


def build_distribution_actions(
    registry: Registry,
    targets: dict[str, SkillTarget],
    root: Path = ROOT,
) -> list[DistributionAction]:
    actions: list[DistributionAction] = []
    for skill in sorted(registry.skills.values(), key=lambda item: (item.source_id, item.name)):
        if not _skill_distribution_enabled(registry, skill):
            continue
        source = _skill_source_for_distribution(registry, skill, root)
        if source is None:
            continue
        if skill.scope == "project":
            for project_name in skill.projects:
                for _, base in _project_targets(registry, project_name, root):
                    actions.append(
                        DistributionAction(
                            skill_name=skill.name,
                            source=source,
                            target_agent=None,
                            target_path=base / skill.name,
                            action="link-dir",
                        )
                    )
            continue
        for agent in skill.agents:
            target = targets[agent]
            base = expand_target_path(target.path, root)
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
        if not _skill_distribution_enabled(registry, skill):
            continue
        if skill.scope == "project":
            for project_name in skill.projects:
                for target_name, _ in _project_targets(registry, project_name, root):
                    specs.add(("project", target_name, skill.name))
            continue
        for agent in skill.agents:
            if agent in targets:
                specs.add(("global", agent, skill.name))
    return specs


def _source_for_legacy_reconcile(registry: Registry, skill: SkillRef, root: Path) -> Path | None:
    """Return an existing source without requiring an enabled distribution gate."""
    source = _skill_source_path(registry, skill, root)
    return source if source is not None and (source / "SKILL.md").is_file() else None


def _legacy_flat_copy_matches_managed_source(
    path: Path,
    skill_name: str,
    registry: Registry,
    root: Path,
) -> bool:
    try:
        legacy_content = path.read_bytes()
    except OSError:
        return False
    for skill in registry.skills.values():
        if skill.name != skill_name:
            continue
        source = _source_for_legacy_reconcile(registry, skill, root)
        if source is None:
            continue
        if legacy_content == (source / "SKILL.md").read_bytes():
            return True
    return False


def filter_reconcile_actions(
    actions: list[ReconcileAction],
    *,
    surface: str | None = None,
    skill: str | None = None,
    agent: str | None = None,
) -> list[ReconcileAction]:
    if surface:
        actions = [action for action in actions if action.surface == surface]
    if skill:
        actions = [action for action in actions if action.skill_name == skill]
    if agent:
        actions = [action for action in actions if action.target_name == agent]
    return actions


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
        if "flat-md" in target.legacy_formats:
            for child in sorted(base.glob("*.md")):
                skill_name = child.stem
                if not _legacy_flat_copy_matches_managed_source(
                    child,
                    skill_name,
                    registry,
                    root,
                ):
                    continue
                actions.append(
                    ReconcileAction(
                        surface="global",
                        target_name=agent,
                        skill_name=skill_name,
                        target_path=child,
                        action="remove-flat-md",
                        reason="legacy flat-md target format; replaced by directory wiring",
                    )
                )
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

    for project_name in sorted(registry.projects):
        for target_name, base in _project_targets(registry, project_name, root):
            if not base.exists():
                continue
            for child in sorted(base.iterdir()):
                if child.name.startswith("."):
                    continue
                if not (child.is_dir() or child.is_symlink()):
                    continue
                skill_name = child.name
                if ("project", target_name, skill_name) in desired:
                    continue
                action = "remove-symlink" if child.is_symlink() else "skip-real-path"
                reason = "not enabled for this project view in skills-sources.jsonc"
                if action == "skip-real-path":
                    reason += "; real directory is left untouched"
                actions.append(
                    ReconcileAction(
                        surface="project",
                        target_name=target_name,
                        skill_name=skill_name,
                        target_path=child,
                        action=action,  # type: ignore[arg-type]
                        reason=reason,
                    )
                )
    return actions


def apply_reconcile_actions(
    actions: list[ReconcileAction],
    *,
    apply: bool = False,
    remove_real_paths: bool = False,
) -> None:
    for action in actions:
        prefix = "APPLY" if apply else "DRY-RUN"
        print(
            f"{prefix} {action.action} {action.surface}/{action.target_name}/{action.skill_name} "
            f"{action.target_path} # {action.reason}"
        )
        if not apply:
            continue
        if action.action == "skip-real-path":
            if remove_real_paths and action.target_path.is_dir() and not action.target_path.is_symlink():
                shutil.rmtree(action.target_path)
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
        if not action.target_path.is_absolute():
            raise RegistryError(f"refusing distribution to non-absolute target path: {action.target_path}")
        home = Path.home()
        # Block filesystem root, shallow system paths (/etc, /usr, ...), $HOME itself,
        # and every ancestor of $HOME (/Users, ...). Legit targets are always
        # <skills_dir>/<skill-name> at depth >= 3 under $HOME.
        if (
            len(action.target_path.parts) <= 2
            or action.target_path == home
            or action.target_path in home.parents
        ):
            raise RegistryError(f"refusing distribution to unsafe root/home target path: {action.target_path}")

        action.target_path.parent.mkdir(parents=True, exist_ok=True)
        if action.action == "copy-flat-md":
            shutil.copyfile(action.source / "SKILL.md", action.target_path)
            continue
        if action.target_path.is_symlink() or action.target_path.is_file():
            action.target_path.unlink()
        elif action.target_path.is_dir():
            print(
                f"WARN: replacing unmanaged directory '{action.target_path}' with symlink to '{action.source}'",
                file=sys.stderr,
            )
            shutil.rmtree(action.target_path)
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
    for project_name in sorted(registry.projects):
        for target_name, base in _project_targets(registry, project_name, root):
            skills = _snapshot_skill_dir(base, flat_md=False)
            project_targets[target_name] = {
                "path": str(base),
                "format": "directory",
                "count": len(skills),
                "skills": skills,
            }
            counts["project_total_entries"] += len(skills)
    return snapshot


def snapshot_output_path(registry: Registry, root: Path, label: str, now: str) -> Path:
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "snapshot"
    return root / registry.paths["snapshot_root"] / f"{now}-{safe_label}.json"


def write_distribution_snapshot(
    registry: Registry, snapshot: dict, root: Path = ROOT, *, label: str
) -> Path:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H%M%SZ")
    path = snapshot_output_path(registry, root, label, now)
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


def validate_runtime_hygiene(
    registry: Registry,
    targets: dict[str, SkillTarget],
    root: Path = ROOT,
) -> list[str]:
    """Scan runtime target directories for forbidden backup residue and divergent realpaths."""
    errors: list[str] = []
    target_dirs: list[tuple[str, Path]] = []
    for target_name, target in sorted(targets.items()):
        target_dirs.append((target_name, expand_target_path(target.path, root)))

    for project_name in sorted(registry.projects):
        target_dirs.extend(_project_targets(registry, project_name, root))

    global_target_names = set(targets.keys())
    seen_skills: dict[str, list[tuple[str, Path, Path]]] = {}

    for target_name, target_dir in target_dirs:
        if not target_dir.is_dir():
            continue
        for child in sorted(target_dir.iterdir()):
            if (
                child.name.endswith(".bak")
                or child.name.endswith(".old")
                or child.name.endswith(".tmp")
                or child.name.endswith("~")
            ):
                errors.append(
                    f"forbidden backup residue in runtime target: {child} (target: {target_name})"
                )
                continue
            # Real (non-symlink) directories are deliberately tracked: runtimes
            # like Codex load every SKILL.md they find, so two real copies of the
            # same skill name in co-scanned views register twice even when their
            # content matches. That is the duplicate-registration bug class this
            # check exists to catch.
            if target_name in global_target_names and (child.is_symlink() or child.is_dir()):
                skill_name = child.name
                try:
                    real = child.resolve()
                except OSError:
                    continue
                seen_skills.setdefault(skill_name, []).append((target_name, child, real))
    # Divergence only breaks de-duplication when ONE runtime co-scans the views.
    # Codex reads ~/.codex/skills AND ~/.agents/skills together; OpenCode reads
    # ~/.config/opencode/skills AND ~/.agents/skills together. Divergence between
    # different runtimes' exclusive views (e.g. claude vs codex) is resolved by
    # provider priority (documented OMP behavior) and is not an error.
    co_scanned_groups: tuple[set[str], ...] = (
        {"codex", "cross-agent"},
        {"opencode", "cross-agent"},
    )

    for group in co_scanned_groups:
        grouped: dict[str, list[tuple[str, Path, Path]]] = {}
        for skill_name, occurrences in seen_skills.items():
            in_group = [occ for occ in occurrences if occ[0] in group]
            if len(in_group) > 1:
                grouped[skill_name] = in_group
        for skill_name, occurrences in sorted(grouped.items()):
            reals = {real for _, _, real in occurrences}
            if len(reals) > 1:
                details = "; ".join(f"{t}: {p} -> {r}" for t, p, r in occurrences)
                errors.append(
                    f"skill '{skill_name}' resolves to divergent realpaths across co-scanned targets "
                    f"({','.join(sorted(group))}): {details}"
                )

    return errors
