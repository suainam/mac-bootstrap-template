#!/usr/bin/env python3
"""Audit agent instruction files (AGENTS.md, CLAUDE.md) for duplicates, mirror drift, and prompt inflation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

HOME = Path.home()
WORK = HOME / "work"
MAX_LINES_LIMIT = 300

GLOBAL_HOSTS = [
    ("Claude", HOME / ".claude" / "CLAUDE.md"),
    ("Codex", HOME / ".codex" / "AGENTS.md"),
    ("OpenCode", HOME / ".config" / "opencode" / "AGENTS.md"),
    ("Pi", HOME / ".pi" / "agent" / "AGENTS.md"),
    ("Gemini/Antigravity", HOME / ".gemini" / "GEMINI.md"),
]


def audit_global_hosts() -> list[dict]:
    results = []
    for host_name, path in GLOBAL_HOSTS:
        exists = path.exists()
        is_symlink = path.is_symlink()
        target = str(path.resolve()) if is_symlink else None
        line_count = len(path.read_text(encoding="utf-8", errors="ignore").splitlines()) if exists else 0
        results.append({
            "host": host_name,
            "path": str(path).replace(str(HOME), "~"),
            "exists": exists,
            "is_symlink": is_symlink,
            "target": target.replace(str(HOME), "~") if target else None,
            "lines": line_count,
        })
    return results


def check_sibling_parity(dir_path: Path) -> tuple[bool, str]:
    """Check whether AGENTS.md and CLAUDE.md in the same directory are identical or aliased."""
    agents = dir_path / "AGENTS.md"
    claude = dir_path / "CLAUDE.md"

    if not agents.exists() or not claude.exists():
        return True, ""

    if agents.is_symlink() and agents.resolve() == claude.resolve():
        return True, "symlinked"
    if claude.is_symlink() and claude.resolve() == agents.resolve():
        return True, "symlinked"

    agents_content = agents.read_text(encoding="utf-8", errors="ignore").strip()
    claude_content = claude.read_text(encoding="utf-8", errors="ignore").strip()

    if agents_content == claude_content:
        return True, "identical"

    if claude_content.startswith("@AGENTS.md") or agents_content.startswith("@CLAUDE.md"):
        return True, "aliased"

    return False, "content_drift"


def audit_workspace_repos() -> tuple[list[dict], list[dict]]:
    file_findings = []
    parity_findings = []

    if not WORK.exists():
        return file_findings, parity_findings

    for root, dirs, files in os.walk(WORK):
        # Exclude build, cache, and vendor directories
        dirs[:] = [
            d for d in dirs
            if d not in {".git", "node_modules", ".venv", "dist", "build", ".pytest_cache", ".uv-cache"}
        ]
        dir_path = Path(root)

        # Check sibling parity if both exist in this directory
        if "AGENTS.md" in files and "CLAUDE.md" in files:
            parity_ok, parity_reason = check_sibling_parity(dir_path)
            if not parity_ok:
                parity_findings.append({
                    "dir": str(dir_path).replace(str(HOME), "~"),
                    "reason": parity_reason,
                })

        for f in files:
            if f in {"AGENTS.md", "CLAUDE.md"}:
                file_path = dir_path / f
                rel_path = str(file_path).replace(str(HOME), "~")
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    lines = [line.strip() for line in content.splitlines() if line.strip()]
                    line_count = len(lines)

                    # Detect duplicate global imports that cause prompt ballooning
                    dup_imports = [
                        l for l in lines
                        if l.startswith("@") and ("12-rules" in l or "RTK" in l)
                    ]

                    warnings = []
                    if dup_imports:
                        warnings.append(f"Redundant global import: {', '.join(dup_imports)}")
                    if line_count > MAX_LINES_LIMIT:
                        warnings.append(f"Excessive line count ({line_count} > {MAX_LINES_LIMIT})")

                    file_findings.append({
                        "path": rel_path,
                        "lines": line_count,
                        "is_symlink": file_path.is_symlink(),
                        "warnings": warnings,
                        "status": "WARN" if warnings else "OK",
                    })
                except Exception as err:
                    file_findings.append({
                        "path": rel_path,
                        "status": "ERROR",
                        "warnings": [f"Read error: {err}"],
                    })

    return file_findings, parity_findings


def main() -> int:
    global_results = audit_global_hosts()
    file_findings, parity_findings = audit_workspace_repos()

    print("=== 1. Agent Global Host Rules ===")
    for item in global_results:
        status = "OK" if item["exists"] else "MISSING"
        symlink_info = f" -> {item['target']}" if item["is_symlink"] else ""
        print(f"  [{status}] {item['host']:<18} {item['path']} ({item['lines']} lines){symlink_info}")

    print("\n=== 2. Workspace Repositories & Subprojects ===")
    warn_count = 0
    for item in file_findings:
        status_label = item["status"]
        if status_label != "OK":
            warn_count += 1
        print(f"  [{status_label}] {item['path']} ({item.get('lines', 0)} lines)")
        for warn in item.get("warnings", []):
            print(f"       ⚠️  {warn}")

    print("\n=== 3. Sibling Parity Check (AGENTS.md ↔ CLAUDE.md) ===")
    if not parity_findings:
        print("  [OK] All repository directories with dual entrypoints (AGENTS.md & CLAUDE.md) are strictly in sync.")
    else:
        for p in parity_findings:
            warn_count += 1
            print(f"  [WARN] {p['dir']} -> AGENTS.md and CLAUDE.md have drifted in content ({p['reason']})")

    print(f"\nAudit complete: {len(file_findings)} rule file(s) checked, {len(parity_findings)} parity check(s), {warn_count} warning(s).")
    return 0 if warn_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
