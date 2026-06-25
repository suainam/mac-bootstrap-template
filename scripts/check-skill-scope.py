#!/usr/bin/env python3
"""Validate first-party skill scope metadata and optional runtime links."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from skill_scope_manifest import load_manifest, normalize_manifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "agent" / "skills-manifest.json"
PROMOTE = ROOT / "agent" / "skills-promote.txt"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def read_promote_personal() -> set[str]:
    names: set[str] = set()
    in_personal = False
    for raw in PROMOTE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("# -- ") or line.startswith("# ── "):
            in_personal = "personal" in line
            continue
        if in_personal and line and not line.startswith("#"):
            names.add(line)
    return names


def expand_path(raw: str) -> Path:
    return Path(
        raw.replace("${HOME}", str(Path.home())).replace("${BOOTSTRAP}", str(ROOT))
    ).expanduser()


def validate_manifest() -> tuple[dict, list[str]]:
    raw = load_manifest(MANIFEST)
    errors: list[str] = []

    try:
        manifest = normalize_manifest(raw)
    except ValueError as exc:
        return {}, [str(exc)]

    if raw.get("version") != 2:
        errors.append("manifest version must be 2")
    if not isinstance(raw.get("global_skills"), list) or not raw.get("global_skills"):
        errors.append("manifest global_skills must be a non-empty array")
    if not isinstance(raw.get("projects"), dict) or not raw.get("projects"):
        errors.append("manifest projects must be a non-empty object")
    if raw.get("source_root") != "agent/skills/personal":
        errors.append("manifest source_root must be agent/skills/personal")

    for skill_name in raw.get("global_skills", []):
        if not NAME_RE.match(skill_name):
            errors.append(f"invalid global skill name: {skill_name}")

    for project_name, project in sorted(raw.get("projects", {}).items()):
        if not NAME_RE.match(project_name):
            errors.append(f"invalid project name: {project_name}")
        if not isinstance(project, dict) or not project.get("skills_dir"):
            errors.append(f"project needs skills_dir: {project_name}")
            continue
        if not isinstance(project.get("skills"), list) or not project.get("skills"):
            errors.append(f"project needs non-empty skills list: {project_name}")
            continue
        for skill_name in project["skills"]:
            if not NAME_RE.match(skill_name):
                errors.append(f"invalid project skill name: {project_name} -> {skill_name}")

    for skill_name, meta in sorted(manifest["skills"].items()):
        source_dir = ROOT / meta["source"]
        try:
            source_dir.relative_to(ROOT / "agent" / "skills" / "personal")
        except ValueError:
            errors.append(f"source must be under agent/skills/personal: {skill_name}")
        if not (source_dir / "SKILL.md").is_file():
            errors.append(f"missing source SKILL.md: {skill_name} -> {source_dir}")

    promote_personal = read_promote_personal()
    manifest_skills = set(manifest["skills"])
    missing_promote = manifest_skills - promote_personal
    missing_manifest = promote_personal - manifest_skills
    for skill_name in sorted(missing_promote):
        errors.append(f"manifest skill missing from personal promote list: {skill_name}")
    for skill_name in sorted(missing_manifest):
        errors.append(f"personal promote skill missing from manifest: {skill_name}")

    return manifest, errors


def validate_runtime(manifest: dict) -> list[str]:
    errors: list[str] = []
    home = Path.home()
    projects = manifest["projects"]
    global_roots = [
        home / ".agent" / "skills" / "personal",
        home / ".codex" / "skills",
        home / ".claude" / "skills",
        home / ".config" / "opencode" / "skills",
        home / ".agents" / "skills",
        home / ".pi" / "agent" / "skills",
        home / ".gemini" / "antigravity-cli" / "skills",
    ]

    for skill_name, meta in sorted(manifest["skills"].items()):
        source = ROOT / meta["source"]
        if meta["scope"] == "global":
            dest = home / ".agent" / "skills" / "personal" / skill_name
            if not dest.is_symlink():
                errors.append(f"global first-party link missing: {dest}")
            elif dest.readlink() != source:
                errors.append(f"global first-party link target mismatch: {dest}")
            continue

        project = projects[meta["project"]]
        dest = expand_path(project["skills_dir"]) / skill_name
        if not dest.is_symlink():
            errors.append(f"project skill link missing: {dest}")
        elif dest.readlink() != source:
            errors.append(f"project skill link target mismatch: {dest}")
        for root in global_roots:
            leaked = root / skill_name
            if leaked.exists() or leaked.is_symlink():
                errors.append(f"project skill leaked into global view: {leaked}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="also validate currently generated symlink views on this machine",
    )
    args = parser.parse_args()

    manifest, errors = validate_manifest()
    if args.runtime and manifest:
        errors.extend(validate_runtime(manifest))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    mode = "runtime" if args.runtime else "static"
    print(
        f"ok skill scope {mode}: skills={len(manifest['skills'])} projects={len(manifest['projects'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
