#!/usr/bin/env python3
"""Content checks for documentation so docs-only pushes cannot skip checks.

Checks, per Markdown file:
  * relative links resolve to an existing file on disk (URLs and pure anchors skipped)
  * fenced ```bash/```sh/```shell blocks parse under ``bash -n`` (never executed)
  * no secret-looking flag is fed a literal or command-substitution value as argv

Usage: check_docs.py [PATH ...]   (PATH = file or directory; default: cwd recursively)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

SKIP_DIRS = {
    ".git",
    ".venv",
    ".agents",
    ".claude",
    ".cache",
    ".pytest_cache",
    ".ruff_cache",
    ".worktrees",
    ".dispatch",
    ".scratch",
    "node_modules",
    "__pycache__",
    "output",
    ".omo",
    ".reasonix",
    ".rtk-state",
    ".commandcode",
    ".workspace",
    ".playwright-cli",
    "archive",
    "quarantine",
}

DOC_SUFFIXES = (".md", ".mdx")

FENCE_RE = re.compile(
    r"^(?P<indent>[ \t]*)```(?P<lang>[A-Za-z0-9_+.-]*)[^\n]*\n"
    r"(?P<body>.*?)^[ \t]*```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?")
SECRET_WORDS = {
    "token",
    "tokens",
    "secret",
    "secrets",
    "passwd",
    "password",
    "apikey",
    "credential",
    "credentials",
    "bearer",
    "key",
}
SECRET_FLAG_RE = re.compile(r"^--?[A-Za-z0-9][A-Za-z0-9-]*$")
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
ARGV_RE = re.compile(
    r"(?<![\w-])(--?[A-Za-z0-9][A-Za-z0-9-]*)"
    r"(?:[=\s]+|(?==))"
    r"(\"[^\"]*\"|'[^']*'|[^\s|;&]+)?"
)
# Documented placeholder forms that stand in for a secret in examples.
PLACEHOLDER_RE = re.compile(r"^(?:<[^>]*>|\{\{[^}]*\}\}|`[^`]*`)$")
# Angle-bracket and double-brace placeholders are documentation, not shell:
# `cmd <table>` is a syntax error to bash, so parse a neutral stand-in instead.
ANGLE_PLACEHOLDER_RE = re.compile(r"(?<!<)<[^<>\s][^<>]*>")
BRACE_PLACEHOLDER_RE = re.compile(r"\{\{[^{}]*\}\}")


def _shell_parse_body(body: str) -> str:
    """Replace documented placeholders so `bash -n` still catches real errors."""
    return BRACE_PLACEHOLDER_RE.sub("placeholder", ANGLE_PLACEHOLDER_RE.sub("placeholder", body))


def _is_secret_flag(flag: str) -> bool:
    words = [word for word in flag.lstrip("-").lower().replace("_", "-").split("-") if word]
    return any(word in SECRET_WORDS for word in words) or "".join(words) in SECRET_WORDS

SHELL_LANGS = {"", "bash", "sh", "shell", "zsh"}


class Finding:
    def __init__(self, path: Path, line: int, message: str) -> None:
        self.path = path
        self.line = line
        self.message = message

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def iter_docs(paths: Iterable[Path]) -> Iterable[Path]:
    for root in paths:
        if root.is_file():
            if root.suffix in DOC_SUFFIXES:
                yield root
            continue
        if not root.is_dir():
            continue
        for current, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                name for name in dirnames if name not in SKIP_DIRS and not name.startswith(".tmp")
            )
            for name in sorted(filenames):
                candidate = Path(current) / name
                if candidate.suffix in DOC_SUFFIXES:
                    yield candidate


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _fences(text: str) -> list[tuple[int, str, str]]:
    """(offset, language, body) for every fenced block."""
    blocks: list[tuple[int, str, str]] = []
    for match in FENCE_RE.finditer(text):
        blocks.append((match.start(), match.group("lang").lower(), match.group("body")))
    return blocks


def _shell_blocks(blocks: list[tuple[int, str, str]]) -> list[tuple[int, str]]:
    """Fenced blocks worth parsing as shell, with their absolute line offsets."""
    shell: list[tuple[int, str]] = []
    for offset, lang, body in blocks:
        if lang not in SHELL_LANGS or not body.strip():
            continue
        # Untagged fences are prose samples unless they look like shell commands.
        if lang == "" and not re.search(
            r"(?m)^[ \t]*(?:#!.*(?:ba)?sh|\$ |sudo |export |cd |brew |make |git )", body
        ):
            continue
        shell.append((offset, body))
    return shell


def check_file(path: Path) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding(path, 1, f"unreadable: {exc}")]
    blocks = _fences(text)
    fenced_spans = [(m.start(), m.end()) for m in FENCE_RE.finditer(text)]
    code_spans = fenced_spans + [(m.start(), m.end()) for m in INLINE_CODE_RE.finditer(text)]
    findings: list[Finding] = []

    for match in LINK_RE.finditer(text):
        if any(start <= match.start() < end for start, end in code_spans):
            continue
        target = match.group(1)
        if target.startswith("#") or "://" in target or target.startswith(
            ("mailto:", "tel:", "//")
        ):
            continue
        raw = target.split("#", 1)[0].strip()
        if not raw or raw.startswith("/"):
            continue
        if not (path.parent / raw).exists():
            findings.append(
                Finding(
                    path,
                    _line_of(text, match.start()),
                    f"broken relative link: {raw}",
                )
            )
    for offset, body in _shell_blocks(blocks):
        result = subprocess.run(
            ["bash", "-n"],
            input=_shell_parse_body(body),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr.strip().splitlines() or ["parse error"])[0]
            findings.append(
                Finding(path, _line_of(text, offset), f"shell block does not parse: {detail}")
            )
        base = _line_of(text, offset)
        for number, line in enumerate(body.splitlines(), start=1):
            for match in ARGV_RE.finditer(line):
                flag, value = match.group(1), match.group(2) or ""
                if not SECRET_FLAG_RE.match(flag) or not _is_secret_flag(flag):
                    continue
                bare = value.strip("\"'")
                if not bare or NUMBER_RE.match(bare):
                    continue
                # Documented safe patterns: placeholders and environment variables.
                if PLACEHOLDER_RE.match(bare) or (
                    bare.startswith("$") and not bare.startswith("$(")
                ):
                    continue
                findings.append(
                    Finding(
                        path,
                        base + number - 1,
                        f"secret value in command-line argv: {flag} {value}",
                    )
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    paths = [Path(item).expanduser().resolve() for item in args] or [Path.cwd()]
    docs = list(iter_docs(paths))
    findings: list[Finding] = []
    for doc in docs:
        findings.extend(check_file(doc))
    for finding in findings:
        print(str(finding), file=sys.stderr)
    if findings:
        print(
            f"check_docs: {len(findings)} issue(s) across {len(docs)} doc(s)", file=sys.stderr
        )
        return 1
    print(f"check_docs: {len(docs)} doc(s) clean", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
