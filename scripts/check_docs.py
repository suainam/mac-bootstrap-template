#!/usr/bin/env python3
"""Content checks for documentation so docs-only pushes cannot skip checks.

Checks, per Markdown file:
  * relative links resolve to an existing file on disk (URLs and pure anchors skipped)
  * fenced ```bash/```sh/```shell blocks parse under ``bash -n`` (never executed)
  * no secret-looking flag is fed a literal or command-substitution value as argv
  * `make <target>` references name a target the owning Makefile defines
    (read as text; the parent catch-all is resolved through ``template/Makefile``)
  * paths in an ``权威来源`` table column exist in the owning repository

Documents that describe unimplemented work opt out per file with
``<!-- check-docs: historical -->``.

Usage: check_docs.py [PATH ...]   (PATH = file or directory; default: cwd recursively)
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
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
# `make` counts only as a command word at the start of a statement; prose such as
# "make sure" inside a sentence is never scanned.
MAKE_COMMAND_RE = re.compile(r"(?:^|[;&|]\s*|\$\s+|(?:rtk|sudo)\s+|\w+=\S*\s+)make(?:\s+|$)")
MAKE_FLAGS_WITH_VALUE = {"-C", "-f", "--file", "--directory", "--makefile"}
# A `cd` leaves this repository, so later `make` lines belong to another one.
CD_COMMAND_RE = re.compile(r"^\s*(?:cd|pushd)\s+")
MAKE_FLAGS = {
    "-B", "-e", "-i", "-I", "-j", "-k", "-l", "-n", "-O", "-o", "-p", "-q", "-r",
    "-s", "-t", "-w", "--always-make", "--dry-run", "--environment-overrides",
    "--ignore-errors", "--jobs", "--just-print", "--keep-going", "--no-builtin-rules",
    "--no-print-directory", "--print-data-base", "--question", "--silent",
    "--touch", "--warn-undefined-variables",
}
TARGET_RULE_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_. -]*?)\s*:(?!=)")
PHONY_RE = re.compile(r"^\.PHONY\s*:(.*)$")
CATCH_ALL_RE = re.compile(r"^%:", re.MULTILINE)
AUTHORITY_COLUMN = "权威来源"
PATH_TOKEN_SUFFIXES = (".md", ".mdx", ".py", ".sh", ".json", ".jsonc", ".yml", ".yaml", ".txt", ".toml", ".cfg")
BRACE_EXPANSION_RE = re.compile(r"\{([^{}]+)\}")
HISTORICAL_MARKER_RE = re.compile(r"<!--\s*check-docs:\s*historical\b")


def _makefile_targets(makefile: Path) -> set[str] | None:
    """Targets defined by one Makefile, read as text (never executed)."""
    try:
        text = makefile.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    targets: set[str] = set()
    for line in text.splitlines():
        if line.startswith(("\t", "#")):
            continue
        rule = TARGET_RULE_RE.match(line)
        if rule:
            targets.update(name for name in rule.group(1).split() if name)
            continue
        phony = PHONY_RE.match(line)
        if phony:
            targets.update(name for name in phony.group(1).replace("\\", " ").split() if name)
    if CATCH_ALL_RE.search(text):
        forwarded = _makefile_targets(makefile.parent / "template" / "Makefile")
        if forwarded:
            targets |= forwarded
    return targets


_TARGET_CACHE: dict[Path, set[str] | None] = {}


def _defined_targets(makefile: Path) -> set[str] | None:
    key = makefile.resolve()
    if key not in _TARGET_CACHE:
        _TARGET_CACHE[key] = _makefile_targets(key)
    return _TARGET_CACHE[key]


def _makefile_root(doc: Path) -> Path | None:
    """Nearest ancestor of `doc` that carries a Makefile."""
    for parent in doc.resolve().parents:
        if (parent / "Makefile").is_file():
            return parent
    return None


def _owns_make_interface(doc: Path, root: Path) -> bool:
    """True when `doc` documents this repository's own make targets.

    Skill and subproject docs describe other repositories' make interfaces, so
    a missing target there says nothing about this repo. Only the root docs and
    the top-level `docs/` and `agent/` trees are in scope.
    """
    try:
        relative = doc.resolve().relative_to(root)
    except ValueError:
        return False
    return len(relative.parts) == 1 or relative.parts[0] in {"docs", "agent"}


def _make_targets(command: str, root: Path) -> list[str]:
    """Bare goal names from one `make ...` command line."""
    try:
        words = shlex.split(command)[1:]
    except ValueError:
        return []
    makefile = root / "Makefile"
    index = 0
    while index < len(words):
        word = words[index]
        if word in MAKE_FLAGS_WITH_VALUE:
            if word in {"-C", "--directory"} and index + 1 < len(words):
                directory = (root / words[index + 1]).resolve()
                makefile = directory / "Makefile"
            index += 2
            continue
        if word.startswith(("-C", "--directory=")):
            value = word.split("=", 1)[1] if "=" in word else word[2:]
            makefile = (root / value).resolve() / "Makefile"
            index += 1
            continue
        if word.startswith("-"):
            index += 1
            continue
        break

    targets = _defined_targets(makefile)
    if targets is None:
        return []

    unknown: list[str] = []
    for word in words[index:]:
        if word in {"&&", "||", ";", "|", "\\", "#"} or word.startswith("#"):
            break

        token = word.strip("\"'")
        if not token:
            continue
        if token.startswith("-") or "=" in token or token.startswith(("<", "{", "[")):
            continue
        if "$" in token or "*" in token or "?" in token or "/" in token:
            continue
        if token not in targets:
            unknown.append(token)
    return unknown


def _authority_paths(text: str) -> list[tuple[int, str]]:
    """(line, path) for path-like backtick tokens in an 权威来源 table column."""
    found: list[tuple[int, str]] = []
    header: int | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            header = None
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if AUTHORITY_COLUMN in cells:
            header = cells.index(AUTHORITY_COLUMN)
            continue
        if header is None or header >= len(cells):
            continue
        for token in re.findall(r"`([^`]+)`", cells[header]):
            for expanded in _expand_braces(token.strip()):
                if not _looks_like_path(expanded):
                    continue
                found.append((number, expanded.rstrip("/")))
    return found


def _expand_braces(token: str) -> list[str]:
    match = BRACE_EXPANSION_RE.search(token)
    if not match:
        return [token]
    head, tail = token[: match.start()], token[match.end() :]
    return [
        expanded
        for choice in match.group(1).split(",")
        for expanded in _expand_braces(head + choice + tail)
    ]


def _looks_like_path(token: str) -> bool:
    if not token or token.startswith(("~", "http", "/", "$", "-")):
        return False
    if any(char in token for char in "*?<>{}"):
        return False
    if " " in token:
        return False
    return "/" in token or token.endswith(PATH_TOKEN_SUFFIXES)


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
    if HISTORICAL_MARKER_RE.search(text):
        return findings

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
        base = _line_of(text, offset) + 1
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
    findings.extend(_check_make_targets(path, text, blocks, fenced_spans))
    findings.extend(_check_authority_paths(path, text))
    return findings


def _check_make_targets(
    path: Path, text: str, blocks: list[tuple[int, str, str]], fenced_spans: list[tuple[int, int]]
) -> list[Finding]:
    """Flag `make <target>` references whose target no Makefile defines."""
    root = _makefile_root(path)
    if root is None or not _owns_make_interface(path, root):
        return []
    findings: list[Finding] = []
    for offset, body in _shell_blocks(blocks):
        base = _line_of(text, offset) + 1
        for number, line in enumerate(body.splitlines(), start=1):
            # A `cd` elsewhere switches to another project's Makefile, whose
            # targets this repository cannot know.
            if CD_COMMAND_RE.match(line):
                break
            for match in MAKE_COMMAND_RE.finditer(line):
                for target in _make_targets(line[match.end() - len("make") :], root):
                    findings.append(
                        Finding(path, base + number - 1, f"unknown make target: {target}")
                    )
    for match in INLINE_CODE_RE.finditer(text):
        if any(start <= match.start() < end for start, end in fenced_spans):
            continue
        span = match.group(0).strip("`").strip()
        command = MAKE_COMMAND_RE.match(span)
        if not command:
            continue
        for target in _make_targets(span[command.end() - len("make") :], root):
            findings.append(
                Finding(path, _line_of(text, match.start()), f"unknown make target: {target}")
            )
    return findings


def _check_authority_paths(path: Path, text: str) -> list[Finding]:
    """Flag 权威来源 table paths that do not exist in the owning repository."""
    root = _makefile_root(path)
    if root is None:
        return []
    return [
        Finding(path, number, f"authority path does not exist: {token}")
        for number, token in _authority_paths(text)
        if not (root / token).exists()
    ]
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
