#!/usr/bin/env python3
"""CLI facade for the skill supply chain modules."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from scripts import skill_registry as _skill_registry
except ModuleNotFoundError:
    import skill_registry as _skill_registry

# Re-export the historical API so existing tests and callers can migrate
# incrementally while the implementation lives in focused modules.
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

try:
    from scripts import skill_distribution as _skill_distribution
except ModuleNotFoundError:
    import skill_distribution as _skill_distribution

globals().update(
    {name: value for name, value in vars(_skill_distribution).items() if not name.startswith("__")}
)

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
    if skill.bundle_id is not None:
        raise RegistryError(
            f"{skill.source_id} is bundle-managed; use fetch-bundle --source {skill.bundle_id}"
        )
    result = fetch_external_skill(skill, registry, ROOT, dry_run=args.dry_run)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode
    if not result.dry_run:
        print(f"fetched external skill {skill.source_id}/{skill.name} -> {skill.quarantine_path}")
    return 0


def select_bundle(registry: Registry, source_id: str) -> SkillBundle:
    try:
        return registry.bundles[source_id]
    except KeyError as exc:
        raise RegistryError(f"unknown bundle: {source_id}") from exc


def cmd_fetch_bundle(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    if not args.source:
        raise RegistryError("fetch-bundle requires --source")
    bundle = select_bundle(registry, args.source)
    result = fetch_external_bundle(bundle, ROOT, dry_run=args.dry_run)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode
    if not result.dry_run:
        print(f"fetched external bundle {bundle.source_id} -> {bundle.quarantine_path}")
    return 0


def cmd_ensure_bundles(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    results = ensure_external_bundles(registry, ROOT, dry_run=args.dry_run)
    if args.dry_run:
        print(f"DRY-RUN bundle fetches: {len(results)}")
    else:
        print(f"ensured external bundles: fetched={len(results)}")
    return 0 if all(result.returncode == 0 for result in results) else 1


def _selected_external_skill(
    args: argparse.Namespace,
    registry: Registry | None = None,
) -> SkillRef:
    registry = registry or load_registry(args.registry)
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
    if args.surface == "global":
        actions = [action for action in actions if action.target_agent is not None]
    elif args.surface == "project":
        actions = [action for action in actions if action.target_agent is None]
    if args.skill:
        actions = [action for action in actions if action.skill_name == args.skill]
    if args.agent:
        actions = [action for action in actions if action.target_agent == args.agent]
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
    actions = filter_reconcile_actions(
        actions,
        surface=args.surface,
        skill=args.skill,
        agent=args.agent,
    )
    should_apply = bool(args.apply)
    if should_apply:
        _assert_safe_apply_root(
            ROOT,
            allow_worktree_apply=os.environ.get("SKILL_SUPPLY_CHAIN_ALLOW_WORKTREE_APPLY") == "1",
        )
    apply_reconcile_actions(actions, apply=should_apply, remove_real_paths=bool(args.remove_real_paths))
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
    path = write_distribution_snapshot(registry, snapshot, ROOT, label=args.label)
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
    registry = load_registry(args.registry)
    skill = _selected_external_skill(args, registry)
    if args.dry_run:
        print(f"DRY-RUN audit external skill {skill.source_id}/{skill.name}")
        return 0
    source = _skill_source_path(registry, skill, ROOT)
    inspection = inspect_skill_content(source) if source and source.is_dir() else None
    decision = evaluate_gate(skill, inspection, audit=None) if inspection else None
    write_run_log(
        {
            "event": "audit",
            "source": skill.source_id,
            "skill": skill.name,
            "result": "pending",
            "reasons": list(decision.reasons) if decision else ["missing quarantine path"],
            "content_hash": inspection.content_hash if inspection else None,
        },
        registry,
        ROOT,
    )
    print(f"audit recorded for {skill.source_id}/{skill.name}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    skill = _selected_external_skill(args, registry)
    if args.dry_run:
        print(f"DRY-RUN diff external skill {skill.source_id}/{skill.name}")
        return 0
    source = _skill_source_path(registry, skill, ROOT)
    if source is None or not source.is_dir():
        raise RegistryError(f"external skill source is unavailable: {skill.source_id}/{skill.name}")
    inspection = inspect_skill_content(source)
    print(json.dumps({"source": skill.source_id, "skill": skill.name, "content_hash": inspection.content_hash}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "plan",
            "fetch",
            "fetch-bundle",
            "ensure-bundles",
            "audit",
            "diff",
            "distribute",
            "reconcile",
            "snapshot",
            "snapshot-diff",
            "check",
        ],
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
    parser.add_argument(
        "--remove-real-paths",
        action="store_true",
        help="allow reconcile to delete real directories; use only with narrow --surface/--skill filters",
    )
    parser.add_argument(
        "--surface",
        choices=["global", "project"],
        help="filter distribute or reconcile actions to one distribution surface",
    )
    parser.add_argument(
        "--agent",
        choices=sorted(VALID_AGENTS),
        help="filter distribute or reconcile actions to one global agent target",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            return cmd_plan(args)
        if args.command == "fetch":
            return cmd_fetch(args)
        if args.command == "fetch-bundle":
            return cmd_fetch_bundle(args)
        if args.command == "ensure-bundles":
            return cmd_ensure_bundles(args)
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
