#!/usr/bin/env python3
"""Normalize and query first-party skill scope manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_SOURCE_ROOT = "agent/skills/personal"


def load_manifest(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def normalize_manifest(manifest: dict) -> dict:
    version = manifest.get("version", 1)
    source_root = manifest.get("source_root", DEFAULT_SOURCE_ROOT)
    projects = manifest.get("projects", {})
    normalized_projects: dict[str, dict] = {}
    normalized_skills: dict[str, dict] = {}

    if version == 1:
        for project_name, project in projects.items():
            normalized_projects[project_name] = {
                "skills_dir": project.get("skills_dir"),
                "skills": [],
            }
        for skill_name, meta in manifest.get("skills", {}).items():
            entry = {
                "scope": meta.get("scope", "global"),
                "source": meta.get("source", f"{source_root}/{skill_name}"),
            }
            project_name = meta.get("project")
            if project_name:
                entry["project"] = project_name
                normalized_projects.setdefault(
                    project_name,
                    {"skills_dir": None, "skills": []},
                )["skills"].append(skill_name)
            normalized_skills[skill_name] = entry
    elif version == 2:
        for skill_name in manifest.get("global_skills", []):
            normalized_skills[skill_name] = {
                "scope": "global",
                "source": f"{source_root}/{skill_name}",
            }
        for project_name, project in projects.items():
            skills = list(project.get("skills", []))
            normalized_projects[project_name] = {
                "skills_dir": project.get("skills_dir"),
                "skills": skills,
            }
            for skill_name in skills:
                normalized_skills[skill_name] = {
                    "scope": "project",
                    "project": project_name,
                    "source": f"{source_root}/{skill_name}",
                }
    else:
        raise ValueError(f"unsupported manifest version: {version}")

    for project in normalized_projects.values():
        project["skills"] = sorted(set(project.get("skills", [])))

    return {
        "version": version,
        "source_root": source_root,
        "projects": normalized_projects,
        "skills": normalized_skills,
    }


def emit_project_lines(path: Path) -> int:
    manifest = normalize_manifest(load_manifest(path))
    for skill_name, meta in sorted(manifest["skills"].items()):
        if meta["scope"] != "project":
            continue
        project = manifest["projects"].get(meta["project"], {})
        print(
            f"{skill_name}\t{meta['source']}\t{meta['project']}\t{project.get('skills_dir', '')}"
        )
    return 0


def emit_skill_scope(path: Path, skill_name: str) -> int:
    manifest = normalize_manifest(load_manifest(path))
    print(manifest["skills"].get(skill_name, {}).get("scope", "global"))
    return 0


def emit_skill_source(path: Path, skill_name: str) -> int:
    manifest = normalize_manifest(load_manifest(path))
    print(manifest["skills"].get(skill_name, {}).get("source", f"{DEFAULT_SOURCE_ROOT}/{skill_name}"))
    return 0


def emit_global_skills(path: Path) -> int:
    manifest = normalize_manifest(load_manifest(path))
    for skill_name, meta in sorted(manifest["skills"].items()):
        if meta["scope"] == "global":
            print(skill_name)
    return 0


def emit_non_global_skills(path: Path) -> int:
    manifest = normalize_manifest(load_manifest(path))
    for skill_name, meta in sorted(manifest["skills"].items()):
        if meta["scope"] != "global":
            print(skill_name)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("manifest", type=Path)

    subparsers.add_parser("project-lines", parents=[base])

    skill_scope = subparsers.add_parser("skill-scope", parents=[base])
    skill_scope.add_argument("skill_name")

    skill_source = subparsers.add_parser("skill-source", parents=[base])
    skill_source.add_argument("skill_name")

    subparsers.add_parser("global-skills", parents=[base])
    subparsers.add_parser("non-global-skills", parents=[base])

    args = parser.parse_args()
    if args.command == "project-lines":
        return emit_project_lines(args.manifest)
    if args.command == "skill-scope":
        return emit_skill_scope(args.manifest, args.skill_name)
    if args.command == "skill-source":
        return emit_skill_source(args.manifest, args.skill_name)
    if args.command == "global-skills":
        return emit_global_skills(args.manifest)
    if args.command == "non-global-skills":
        return emit_non_global_skills(args.manifest)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
