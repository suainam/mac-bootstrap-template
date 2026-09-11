#!/usr/bin/env python3
"""Audit repository knowledge boundaries without mutating the repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "curate-repo-knowledge.audit/v1"
PERSISTENT_BUDGET = {
    "total_lines": 80,
    "estimated_tokens": 1_000,
    "bytes": 8_192,
}
ROUTING_BUDGET = {
    "total_lines": 100,
    "estimated_tokens": 1_500,
}
ROUTING_PATHS = {"CONTEXT.md", "docs/README.md"}
AGENT_PATHS = ("AGENTS.md", "CLAUDE.md")
SKIP_PARTS = {
    ".git",
    ".venv",
    ".worktrees",
    "node_modules",
    "vendor",
    "archive",
    "archive_plans",
    "retrospectives",
    "artifacts",
}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FENCED_CODE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
CHINESE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
TSD_HEADER = b"%TSD-Header-###%"


class TSDWrappedMarkdown(UnicodeError):
    """A Markdown path contains a Codex TSD wrapper on disk."""


def estimated_tokens(text: str) -> int:
    """Return a conservative deterministic estimate for mixed CJK/Latin text."""
    cjk_count = len(CHINESE.findall(text))
    non_cjk = CHINESE.sub("", text)
    return cjk_count + math.ceil(len(non_cjk.encode("utf-8")) / 4)


def measurement(path: Path) -> dict[str, int | str]:
    data = path.read_bytes()
    if data.startswith(TSD_HEADER):
        raise TSDWrappedMarkdown(path.as_posix())
    text = data.decode("utf-8")
    return {
        "total_lines": len(text.splitlines()),
        "non_empty_lines": sum(bool(line.strip()) for line in text.splitlines()),
        "estimated_tokens": estimated_tokens(text),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def active_markdown_files(root: Path) -> list[Path]:
    repository = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if repository.returncode == 0:
        listed = subprocess.run(
            [
                "git",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                "*.md",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )
        candidates = [
            root / os.fsdecode(raw_path)
            for raw_path in listed.stdout.split(b"\0")
            if raw_path
        ]
    else:
        candidates = list(root.rglob("*.md"))

    files: list[Path] = []
    for path in candidates:
        parts = path.relative_to(root).parts
        if any(part.casefold() in SKIP_PARTS for part in parts):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def uninitialized_submodule_paths(root: Path) -> list[Path]:
    """Return tracked gitlinks whose working-tree directories are unavailable."""
    listed = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if listed.returncode != 0:
        return []

    paths: list[Path] = []
    for record in listed.stdout.split(b"\0"):
        metadata, separator, raw_path = record.partition(b"\t")
        if not separator or not metadata.startswith(b"160000 "):
            continue
        path = root / os.fsdecode(raw_path)
        worktree = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
        if (
            worktree.returncode != 0
            or Path(worktree.stdout.strip()).resolve() != path.resolve()
        ):
            paths.append(path)
    return paths


def agent_source(root: Path) -> dict[str, Any]:
    present = [
        root / name
        for name in AGENT_PATHS
        if (root / name).exists() or (root / name).is_symlink()
    ]
    if not present:
        return {"status": "missing", "canonical_path": None, "aliases": []}
    if len(present) == 1:
        return {
            "status": "single-source",
            "canonical_path": present[0].name,
            "aliases": [],
        }

    agents = root / "AGENTS.md"
    claude = root / "CLAUDE.md"
    if agents.is_symlink() and agents.exists() and agents.resolve() == claude.resolve():
        return {
            "status": "single-source",
            "canonical_path": "CLAUDE.md",
            "aliases": ["AGENTS.md"],
        }
    if claude.is_symlink() and claude.exists() and claude.resolve() == agents.resolve():
        return {
            "status": "single-source",
            "canonical_path": "AGENTS.md",
            "aliases": ["CLAUDE.md"],
        }
    return {
        "status": "conflict",
        "canonical_path": None,
        "aliases": [],
    }


def finding(
    code: str,
    severity: str,
    path: str,
    evidence: dict[str, Any],
    mutation_class: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "path": path,
        "evidence": evidence,
        "mutation_class": mutation_class,
    }


def budget_findings(
    relative: str, values: dict[str, int | str], budget: dict[str, int]
) -> list[dict[str, Any]]:
    results = []
    prefix = "PERSISTENT" if relative in AGENT_PATHS else "ROUTING"
    metric_names = {
        "total_lines": "LINE",
        "non_empty_lines": "LINE",
        "estimated_tokens": "TOKEN",
        "bytes": "BYTE",
    }
    for metric, limit in budget.items():
        value = values[metric]
        if isinstance(value, int) and value > limit:
            results.append(
                finding(
                    f"{prefix}_{metric_names[metric]}_BUDGET_EXCEEDED",
                    "error" if prefix == "PERSISTENT" else "warning",
                    relative,
                    {"metric": metric, "actual": value, "limit": limit},
                    "review-required",
                )
            )
    return results


def local_link_findings(
    root: Path,
    paths: list[tuple[Path, str]],
    uninitialized_submodules: list[Path],
) -> list[dict[str, Any]]:
    results = []
    for path, relative in paths:
        if path.is_symlink():
            continue
        text = FENCED_CODE.sub("", path.read_text(encoding="utf-8"))
        for target in MARKDOWN_LINK.findall(text):
            raw = target.strip()
            if raw.startswith("<") and ">" in raw:
                clean = raw[1 : raw.index(">")]
            else:
                try:
                    parts = shlex.split(raw)
                except ValueError:
                    parts = [raw]
                clean = parts[0] if parts else ""
            clean = clean.split("#", 1)[0]
            if not clean or "://" in clean or clean.startswith(("mailto:", "#")):
                continue
            candidate = ((root / relative).parent / clean).resolve()
            if not candidate.is_relative_to(root):
                results.append(
                    finding(
                        "LOCAL_LINK_ESCAPES_ROOT",
                        "error",
                        relative,
                        {"target": target},
                        "review-required",
                    )
                )
                continue
            if any(candidate.is_relative_to(submodule) for submodule in uninitialized_submodules):
                continue
            if not candidate.exists():
                results.append(
                    finding(
                        "DEAD_LOCAL_LINK",
                        "error",
                        relative,
                        {"target": target},
                        "safe-auto-repair",
                    )
                )
    return results


def duplicate_candidates(
    root: Path, paths: list[tuple[Path, str]]
) -> list[dict[str, Any]]:
    occurrences: dict[str, list[str]] = defaultdict(list)
    for path, relative in paths:
        if path.is_symlink():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            normalized = " ".join(line.strip().split())
            if (
                len(normalized) < 40
                or normalized.startswith(
                    (
                        "#",
                        "```",
                        "-",
                        "*",
                        ">",
                        "|",
                        "[",
                        "{",
                        "1.",
                        "2.",
                        "3.",
                        "4.",
                        "5.",
                        "6.",
                        "7.",
                        "8.",
                        "9.",
                    )
                )
                or "`" in normalized
            ):
                continue
            occurrences[normalized].append(relative)

    results = []
    for text, locations in sorted(occurrences.items()):
        unique_locations = sorted(set(locations))
        if len(unique_locations) < 2:
            continue
        results.append(
            finding(
                "POSSIBLE_DUPLICATE_FACT",
                "candidate",
                unique_locations[0],
                {"locations": unique_locations, "text": text},
                "review-required",
            )
        )
    return results


def _load_materializations(
    root: Path, manifest_paths: list[Path]
) -> tuple[dict[str, tuple[Path, Path]], list[dict[str, Any]]]:
    mappings: dict[str, tuple[Path, Path]] = {}
    findings: list[dict[str, Any]] = []
    for raw_manifest in manifest_paths:
        manifest = raw_manifest.expanduser().resolve(strict=False)
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            source = Path(str(payload["source"])).expanduser().resolve(strict=False)
            output = Path(str(payload["output"])).expanduser().resolve(strict=False)
            if payload.get("status") != "success" or payload.get("verified") is not True:
                raise ValueError("manifest is not a verified successful materialization")
            relative = source.relative_to(root).as_posix()
            if not source.is_file() or not source.read_bytes().startswith(TSD_HEADER):
                raise ValueError("source is not an existing TSD-wrapped file")
            if output.is_relative_to(root) or not output.is_file():
                raise ValueError("materialized output must be an existing external file")
            data = output.read_bytes()
            data.decode("utf-8")
            if data.startswith(TSD_HEADER):
                raise ValueError("materialized output still has a TSD header")
            if payload.get("bytes") != len(data):
                raise ValueError("materialized byte count does not match manifest")
            if payload.get("sha256") != hashlib.sha256(data).hexdigest():
                raise ValueError("materialized sha256 does not match manifest")
            previous = mappings.get(relative)
            if previous is not None and previous[0] != output:
                raise ValueError("multiple materializations claim the same source")
            mappings[relative] = (output, manifest)
        except (KeyError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            findings.append(
                finding(
                    "INVALID_MATERIALIZATION",
                    "error",
                    manifest.as_posix(),
                    {"reason": str(exc)},
                    "review-required",
                )
            )
    return mappings, findings


def audit(root: Path, materialized_manifests: list[Path] | None = None) -> dict[str, Any]:
    root = root.resolve()
    markdown = active_markdown_files(root)
    uninitialized_submodules = uninitialized_submodule_paths(root)
    materializations, materialization_findings = _load_materializations(
        root, materialized_manifests or []
    )
    measurements = {}
    readable: list[tuple[Path, str]] = []
    findings: list[dict[str, Any]] = list(materialization_findings)
    for path in markdown:
        if path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        try:
            measurements[relative] = measurement(path)
        except (UnicodeError, OSError) as exc:
            materialized = materializations.get(relative)
            if isinstance(exc, TSDWrappedMarkdown) and materialized is not None:
                output, manifest = materialized
                measurements[relative] = {
                    **measurement(output),
                    "materialized_path": output.as_posix(),
                    "materialized_manifest": manifest.as_posix(),
                }
                readable.append((output, relative))
                continue
            code = (
                "ENCRYPTED_MARKDOWN"
                if isinstance(exc, TSDWrappedMarkdown)
                else "UNREADABLE_MARKDOWN"
            )
            findings.append(finding(
                code, "error", relative,
                {
                    "reason": type(exc).__name__,
                    "checks_skipped": [
                        "measurement", "local_links", "duplicate_candidates"
                    ],
                    "remediation": (
                        "materialize to an external temporary path with "
                        "decrypt-materialize; preserve the source"
                        if code == "ENCRYPTED_MARKDOWN"
                        else "inspect encoding or file format"
                    ),
                },
                "review-required",
            ))
        else:
            readable.append((path, relative))
    source = agent_source(root)

    if source["status"] == "conflict":
        findings.append(
            finding(
                "AGENT_AUTHORITY_CONFLICT",
                "error",
                ".",
                {"paths": list(AGENT_PATHS)},
                "review-required",
            )
        )

    canonical = source["canonical_path"]
    if canonical and canonical in measurements:
        findings.extend(
            budget_findings(canonical, measurements[canonical], PERSISTENT_BUDGET)
        )
    for relative in sorted(ROUTING_PATHS):
        if relative in measurements:
            findings.extend(
                budget_findings(relative, measurements[relative], ROUTING_BUDGET)
            )

    findings.extend(local_link_findings(root, readable, uninitialized_submodules))
    findings.extend(duplicate_candidates(root, readable))
    findings.sort(key=lambda item: (item["severity"], item["code"], item["path"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "root": root.as_posix(),
        "budgets": {
            "persistent": PERSISTENT_BUDGET,
            "routing": ROUTING_BUDGET,
        },
        "agent_source": source,
        "submodules": {
            "uninitialized": [
                path.relative_to(root).as_posix()
                for path in uninitialized_submodules
            ]
        },
        "measurements": measurements,
        "materializations": {
            relative: {"output": output.as_posix(), "manifest": manifest.as_posix()}
            for relative, (output, manifest) in materializations.items()
        },
        "findings": findings,
        "summary": {
            "error_count": sum(item["severity"] == "error" for item in findings),
            "warning_count": sum(item["severity"] == "warning" for item in findings),
            "candidate_count": sum(
                item["severity"] == "candidate" for item in findings
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--format", choices=("json",), default="json")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--materialized-manifest",
        action="append",
        type=Path,
        default=[],
        help="verified decrypt-materialize JSON output; may be repeated",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.root.is_dir():
        raise SystemExit(f"project root does not exist: {args.root}")
    report = audit(args.root, args.materialized_manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.strict and report["summary"]["error_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
