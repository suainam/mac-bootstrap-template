#!/usr/bin/env python3
"""Block commits that introduce agent-authored files over a rough token budget.

Single implementation shared by both hook paths:

- trusted dispatcher ``before.commit`` (see ``agent/runtime/registry.jsonc``),
  which supplies staged entries through ``AGENT_RUNTIME_EVENT_JSON``;
- repository self hook ``agent/quality-gates/hooks/pre-commit``, which supplies
  staged paths through the manifest gate list.

Token estimate is deliberately rough: 4 bytes per token for Latin text and one
token per CJK character, so a Chinese document is not charged for UTF-8
expansion. No tokenizer runs here, so the budget is a maintenance guard
against giant agent-authored files, not an exact accounting.
"""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable, Mapping, NamedTuple

# Rough token estimate, no tokenizer. Two byte classes: CJK codepoints cost
# ~1 token per character (3 UTF-8 bytes each), everything else costs ~1 token
# per 4 bytes. A pure-English file of 20000 bytes therefore estimates 5000
# tokens, while a pure-Chinese file reaches the same budget at 18000 bytes,
# which is ~6000 characters.
BYTES_PER_TOKEN = 4
BYTES_PER_CJK_TOKEN = 3
CJK_PATTERN = re.compile(r"[\u3000-\u303f\u3040-\u9fff\uf900-\ufaff\uff00-\uffef]")
# Reading only the first slice keeps binary sniffing cheap for 700 KB blobs.
BINARY_PROBE_BYTES = 8192
GIT_TIMEOUT_SECONDS = 20
MAX_REPORTED_FILES = 10

# Not authored by agents: dependency lockfiles, vendored trees, build output,
# generated bundles, and audited skill shadows. Binary assets are skipped by
# content sniffing instead, so extension lists stay out of the registry.
DEFAULT_IGNORE_GLOBS = (
    "*.lock",
    "*-lock.json",
    "*-lock.yaml",
    "go.sum",
    "dist/**",
    "build/**",
    "vendor/**",
    "node_modules/**",
    "agent-skills/local/shadows/**",
    "agent-skills/external/**",
    "*.min.js",
    "*.min.css",
    "*.min.map",
    "*.map",
    "*.svg",
)


class FileSizeGateError(RuntimeError):
    pass


class StagedFile(NamedTuple):
    path: str
    blob_oid: str | None


def estimate_tokens(data: bytes) -> int:
    """Rough token estimate over raw bytes; no tokenizer is involved.

    CJK characters are counted by codepoint (about one token each) and
    removed from the byte count before the 4-bytes-per-token heuristic is
    applied to the remainder, so a Chinese-heavy document is not penalized
    for UTF-8 expansion. Overhead: decoding is skipped for binary blobs.
    """
    if not data:
        return 0
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return (len(data) + BYTES_PER_TOKEN - 1) // BYTES_PER_TOKEN
    cjk_chars = len(CJK_PATTERN.findall(text))
    cjk_bytes = cjk_chars * BYTES_PER_CJK_TOKEN
    other_bytes = max(len(data) - cjk_bytes, 0)
    return cjk_chars + (other_bytes + BYTES_PER_TOKEN - 1) // BYTES_PER_TOKEN


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=os.environ.copy(),
            capture_output=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise FileSizeGateError(
            f"Git command timed out after {GIT_TIMEOUT_SECONDS}s while measuring staged files"
        ) from exc


def _matches_any_glob(path: str, globs: Iterable[str]) -> bool:
    """Match against the full path, the basename, and every directory suffix.

    The suffix pass makes directory globs such as ``dist/**`` apply at any
    depth, so ``infra/app/dist/bundle.js`` is recognized without listing every
    possible prefix.
    """
    name = Path(path).name
    candidates = [path, name, *_suffix_candidates(path)]
    return any(
        fnmatch.fnmatch(candidate, glob) for glob in globs for candidate in candidates
    )


def _suffix_candidates(path: str) -> list[str]:
    """The path itself plus every suffix starting at a component boundary."""
    parts = path.split("/")
    return ["/".join(parts[start:]) for start in range(len(parts))]


def _blob_bytes(repo_root: Path, oid: str) -> bytes | None:
    result = _run(["git", "cat-file", "blob", oid], cwd=repo_root)
    if result.returncode != 0:
        return None
    return result.stdout


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:BINARY_PROBE_BYTES]


def staged_files_from_event(payload: Mapping[str, Any]) -> list[StagedFile]:
    if payload.get("event_type") != "before.commit":
        raise FileSizeGateError("file size gate requires before.commit")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise FileSizeGateError("before.commit metadata is required")
    entries = metadata.get("staged_entries")
    if not isinstance(entries, list):
        raise FileSizeGateError("before.commit staged_entries are required")
    files: list[StagedFile] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            raise FileSizeGateError("staged entry must be an object")
        if not raw_entry.get("present_in_index"):
            continue
        mode = raw_entry.get("mode")
        if mode == "160000":
            # Gitlink: the submodule repository is checked on its own terms.
            continue
        path = raw_entry.get("path")
        if not isinstance(path, str) or not path:
            raise FileSizeGateError("staged file path is invalid")
        oid = raw_entry.get("blob_oid")
        files.append(
            StagedFile(
                path=path,
                blob_oid=oid if isinstance(oid, str) else None,
            )
        )
    return files


def staged_files_from_git(repo_root: Path) -> list[StagedFile]:
    """Staged regular files with index content, not worktree content.

    Only paths whose index blob differs from HEAD are considered, so an
    untouched file is never re-judged at commit time. Deletions and gitlinks
    are skipped: neither has content to measure.
    """
    result = _run(
        ["git", "diff", "--cached", "--raw", "-z", "--no-abbrev"], cwd=repo_root
    )
    if result.returncode != 0:
        raise FileSizeGateError(
            "cannot read the Git index; run the gate from inside a Git repository"
        )
    tokens = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    files: list[StagedFile] = []
    index = 0
    while index < len(tokens):
        record = tokens[index]
        index += 1
        # Records look like ":<srcmode> <dstmode> <srcsha> <dstsha> <status>".
        if not record.startswith(":"):
            continue
        fields = record.split()
        if len(fields) < 5:
            raise FileSizeGateError(f"unparsable Git raw diff record: {record}")
        status = fields[4]
        if status[0] in {"R", "C"}:
            # With -z a rename or copy carries the source path then the
            # destination path. Only the destination is the file being
            # committed, so ignore globs and the HEAD ratchet must see it.
            path = tokens[index + 1] if index + 1 < len(tokens) else ""
            index += 2
        else:
            path = tokens[index] if index < len(tokens) else ""
            index += 1
        if status[0] == "D" or fields[1] == "160000":
            continue
        if not path or set(fields[3]) == {"0"}:
            continue
        files.append(StagedFile(path=path, blob_oid=fields[3]))
    return files


def _head_blob(repo_root: Path, path: str) -> bytes | None:
    """Committed content of a path, used only for the ratchet comparison."""
    result = _run(["git", "cat-file", "blob", f"HEAD:{path}"], cwd=repo_root)
    if result.returncode != 0:
        return None
    return result.stdout

class OversizedFile(NamedTuple):
    path: str
    tokens: int
    preexisting: bool


def collect_oversized(
    files: list[StagedFile],
    repo_root: Path,
    *,
    limit: int,
    ignore_globs: tuple[str, ...],
) -> tuple[list[OversizedFile], list[OversizedFile]]:
    """Return (blocking, warned) staged files above the rough token limit.

    A file that already exceeded the limit at HEAD is not blocked: the gate is a
    ratchet against newly introduced giants, so existing files stay editable
    and get a warning instead.
    """
    blocking: list[OversizedFile] = []
    warned: list[OversizedFile] = []
    for staged in files:
        if staged.blob_oid is None:
            continue
        if ignore_globs and _matches_any_glob(staged.path, ignore_globs):
            continue
        data = _blob_bytes(repo_root, staged.blob_oid)
        if data is None or _looks_binary(data):
            continue
        tokens = estimate_tokens(data)
        if tokens <= limit:
            continue
        # The ratchet must judge HEAD with the same estimator as the staged
        # blob, so a Chinese file cannot block on an English-only comparison.
        head_blob = _head_blob(repo_root, staged.path)
        if head_blob is not None and estimate_tokens(head_blob) > limit:
            warned.append(OversizedFile(staged.path, tokens, True))
        else:
            blocking.append(OversizedFile(staged.path, tokens, False))
    return blocking, warned


def _repo_root() -> Path:
    raw = os.environ.get("AGENT_RUNTIME_REPO_ROOT", "").strip()
    if raw:
        return Path(raw).resolve()
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=Path.cwd())
    if result.returncode != 0:
        raise FileSizeGateError("cannot resolve the Git repository root")
    return Path(result.stdout.decode("utf-8", errors="surrogateescape").strip()).resolve()


def _configured_limit() -> int:
    raw = os.environ.get("QUALITY_GATES_MAX_FILE_TOKENS", "").strip()
    if not raw:
        return 5000
    try:
        limit = int(raw)
    except ValueError as exc:
        raise FileSizeGateError(
            f"QUALITY_GATES_MAX_FILE_TOKENS must be an integer: {raw}"
        ) from exc
    if limit <= 0:
        raise FileSizeGateError("QUALITY_GATES_MAX_FILE_TOKENS must be positive")
    return limit


def render_report(
    blocking: list[OversizedFile],
    warned: list[OversizedFile],
    *,
    limit: int,
) -> str:
    lines = [
        f"file-size gate: staged agent-authored files exceed the {limit}-token budget "
        f"(rough estimate: {BYTES_PER_TOKEN} bytes per token for Latin text, "
        f"{BYTES_PER_CJK_TOKEN} bytes per CJK character)."
    ]
    for entry in blocking[:MAX_REPORTED_FILES]:
        lines.append(f"  BLOCK {entry.path}: ~{entry.tokens} tokens")
    if len(blocking) > MAX_REPORTED_FILES:
        lines.append(f"  ... and {len(blocking) - MAX_REPORTED_FILES} more")
    lines.append("Split before committing:")
    lines.append("  1. Move independent sections into sibling files and keep an index that links them.")
    lines.append("  2. Split code by responsibility into cohesive modules instead of one large file.")
    lines.append("  3. Extract long examples into references/ and keep short representative snippets.")
    lines.append("  4. Move generated or vendored content out of the repo; regenerate it from its source.")
    lines.append("Then stage the split files and commit again.")
    for entry in warned[:MAX_REPORTED_FILES]:
        lines.append(
            f"  WARN {entry.path}: ~{entry.tokens} tokens (already over budget at HEAD; not blocking)"
        )
    if len(warned) > MAX_REPORTED_FILES:
        lines.append(f"  ... and {len(warned) - MAX_REPORTED_FILES} more pre-existing oversized files")
    return "\n".join(lines)


def check() -> None:
    repo_root = _repo_root()
    raw_event = os.environ.get("AGENT_RUNTIME_EVENT_JSON", "").strip()
    if raw_event:
        try:
            payload = json.loads(raw_event)
        except json.JSONDecodeError as exc:
            raise FileSizeGateError(f"invalid runtime event JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise FileSizeGateError("runtime event JSON must be an object")
        files = staged_files_from_event(payload)
    else:
        files = staged_files_from_git(repo_root)
    limit = _configured_limit()
    blocking, warned = collect_oversized(
        files,
        repo_root,
        limit=limit,
        ignore_globs=DEFAULT_IGNORE_GLOBS,
    )
    if warned:
        print(render_report(blocking=[], warned=warned, limit=limit))
    if blocking:
        raise FileSizeGateError(render_report(blocking, warned=[], limit=limit))


def main() -> int:
    try:
        check()
    except FileSizeGateError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
