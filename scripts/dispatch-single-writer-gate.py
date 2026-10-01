#!/usr/bin/env python3
"""Single-writer invariant gate — TB-02.

Herdr's official ``herdr:omp`` integration already owns agent lifecycle
reporting. Its shipped integration keeps four counters and an increasing
``seq``, and Herdr accepts-but-ignores any same-source report whose ``seq`` is
not newer. A second writer therefore does not fail loudly: it silently starves
the official reporter, or flips a pane back to ``idle`` while a retry hold is
active. Neither symptom points back here, which is exactly why this needs to be
a gate rather than a convention.

This gate turns the invariant into a check that fails the build:

1. dispatch-owned code must not report agent *semantic state*;
2. dispatch-owned code must not write Herdr-managed integration files;
3. dispatch-owned code must not attach a session-resume command itself —
   Herdr only accepts one from an agent that already holds the pane through
   semantic reporting, which rule 1 forbids, so the official integration owns
   it (skeptic review S-12).

Reads are explicitly allowed; only the write side is forbidden.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Where dispatch-owned code is allowed to live, relative to the repo root.
# Entries may be files or directories.
DEFAULT_OWNED_PATHS: Tuple[str, ...] = (
    "multiplexer/herdr-dispatch",
    "agent/omp/extensions/dispatch-omp",
    "agent-skills/local/global/dispatch",
)

SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", ".pytest_cache", "dist", "build"}
)
SOURCE_SUFFIXES = frozenset({".py", ".ts", ".js", ".mjs", ".cjs", ".sh", ".bash"})

# Herdr-managed integration files. Owned by the Herdr CLI: reinstalling or
# updating an integration overwrites them, and the shipped header tells authors
# to place custom hooks beside the file rather than edit it.
MANAGED_INTEGRATION_RE = re.compile(
    r"herdr-[a-z0-9_-]*agent-(?:state|session)\.(?:py|sh|js|ts)\b"
)

# Semantic agent states. Reporting one of these is the write we forbid.
SEMANTIC_STATES = ("working", "blocked", "idle", "done", "unknown")

# `pane.report_agent` is the semantic-state report; its CLI wrapper is
# `herdr pane report-agent`. Both spellings must be caught, or the rule is
# trivially bypassed by using the documented command instead of the socket.
# `pane.report_agent_session` / `report-agent-session` is excluded: a session
# reference is not a lifecycle report, and reporting metadata is the sanctioned
# write.
REPORT_SEMANTIC_RE = re.compile(r"report[-_]agent(?![-_]session)")
REPORT_METADATA_RE = re.compile(r"report[-_]metadata")

# Constructing a report payload by hand is the same write by another route.
REPORT_PAYLOAD_RE = re.compile(
    r"\"state\"\s*:\s*\"(?:" + "|".join(SEMANTIC_STATES) + r")\""
)

# Attaching a resume command needs the pane to be held through semantic
# reporting, which rule 1 forbids — so dispatch must not attach one.
RESUME_ARGV_RE = re.compile(r"resume_argv")


@dataclass(frozen=True)
class Violation:
    path: str
    line_no: int
    rule: str
    excerpt: str
    guidance: str


RULES: Dict[str, str] = {
    "semantic-state-report": (
        "dispatch must not report agent lifecycle state (working/blocked/idle). "
        "The Herdr integration `herdr:omp` owns it and tracks retry holds and "
        "blocked counters internally; a second writer makes Herdr accept-and-"
        "ignore its reports. Read `agent_status` / `state_change_seq` instead."
    ),
    "managed-integration-edit": (
        "Herdr-managed integration files are owned by the `herdr` CLI and are "
        "overwritten on reinstall. Their header says to place custom hooks "
        "beside the file. Put dispatch code in its own extension file."
    ),
    "self-resume-argv": (
        "Herdr only accepts a resume command from an agent that already holds "
        "the pane via semantic reporting, which the first rule forbids. Record "
        "and validate the expected resume command in the state file; let "
        "`herdr:omp` attach it (skeptic review S-12)."
    ),
}


def iter_source_files(roots: Iterable[Path]) -> List[Path]:
    out: List[Path] = []
    for root in roots:
        if root.is_file():
            if root.suffix in SOURCE_SUFFIXES:
                out.append(root)
            continue
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix in SOURCE_SUFFIXES:
                out.append(path)
    return out


COMMENT_PREFIXES = ("#", "//", "<!--", "*", ";")


def _is_comment(line: str) -> bool:
    return line.startswith(COMMENT_PREFIXES)


def _docstring_lines(text: str) -> frozenset[int]:
    """Line numbers occupied by Python docstrings.

    Documentation that explains *why* a call is forbidden must not be mistaken
    for the call. Judging code rather than prose about code keeps the gate's
    findings actionable; without this, every "we deliberately do not call
    report_agent here" comment would need to be worded around the gate.
    """
    try:
        import ast

        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return frozenset()

    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            start = first.lineno
            end = getattr(first, "end_lineno", None) or start
            lines.update(range(start, end + 1))
    return frozenset(lines)


def scan_text(text: str, display_path: str) -> List[Violation]:
    """Check one file's contents for the three forbidden writes."""
    violations: List[Violation] = []
    skip_lines = _docstring_lines(text) if display_path.endswith(".py") else frozenset()
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if line_no in skip_lines:
            continue
        line = raw.strip()
        if not line or _is_comment(line):
            continue

        if MANAGED_INTEGRATION_RE.search(line):
            violations.append(
                Violation(
                    display_path,
                    line_no,
                    "managed-integration-edit",
                    line[:160],
                    RULES["managed-integration-edit"],
                )
            )
            continue

        if REPORT_SEMANTIC_RE.search(line) or REPORT_PAYLOAD_RE.search(line):
            violations.append(
                Violation(
                    display_path,
                    line_no,
                    "semantic-state-report",
                    line[:160],
                    RULES["semantic-state-report"],
                )
            )
            continue

        if RESUME_ARGV_RE.search(line):
            violations.append(
                Violation(
                    display_path,
                    line_no,
                    "self-resume-argv",
                    line[:160],
                    RULES["self-resume-argv"],
                )
            )
            continue

    return violations


def scan_repo(
    root: Path,
    owned_paths: Sequence[str] = DEFAULT_OWNED_PATHS,
) -> List[Violation]:
    """Scan every dispatch-owned source file. Missing paths are not an error."""
    roots = [root / rel for rel in owned_paths]
    present = [p for p in roots if p.exists()]
    violations: List[Violation] = []
    for path in iter_source_files(present):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root).as_posix()
        violations.extend(scan_text(text, rel))
    return violations


def format_report(violations: Sequence[Violation], root: Path) -> str:
    lines = [
        "single-writer invariant violated: dispatch must not take ownership of",
        "agent lifecycle reporting.",
        "",
    ]
    for violation in violations:
        lines.append(f"  {violation.path}:{violation.line_no}  [{violation.rule}]")
        lines.append(f"    {violation.excerpt}")
        lines.append(f"    -> {violation.guidance}")
        lines.append("")
    lines.append(
        "Official contract: https://herdr.dev/docs/socket-api/ "
        "(`pane.report_agent` is owned by the agent's Herdr integration)."
    )
    return "\n".join(lines)


def find_repo_root(start: Optional[Path] = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "template").exists() or (
            (candidate / "agent-skills").is_dir() and (candidate / "scripts").is_dir()
        ):
            return candidate
    return here


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dispatch-single-writer-gate",
        description="Fail when dispatch-owned code writes agent lifecycle state.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="repository root (defaults to the detected bootstrap repo root)",
    )
    parser.add_argument(
        "--owned-path",
        action="append",
        default=None,
        help="override dispatch-owned path (repeatable)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else find_repo_root()
    owned = tuple(args.owned_path) if args.owned_path else DEFAULT_OWNED_PATHS

    violations = scan_repo(root, owned)
    if violations:
        print(format_report(violations, root), file=sys.stderr)
        return 1

    print("single-writer gate: ok (no lifecycle reporting in dispatch-owned code)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())