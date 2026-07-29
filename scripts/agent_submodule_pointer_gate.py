#!/usr/bin/env python3
from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping


OID_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
GIT_TIMEOUT_SECONDS = 20
ALLOWED_PROTOCOL_CONFIG = (
    "protocol.allow=never",
    "protocol.file.allow=always",
    "protocol.https.allow=always",
    "protocol.ssh.allow=always",
)


class PointerGateError(RuntimeError):
    pass


def _run(
    command: list[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PointerGateError(
            f"Git command timed out after {GIT_TIMEOUT_SECONDS}s while checking submodule pointer"
        ) from exc


def _event() -> Mapping[str, Any]:
    raw = os.environ.get("AGENT_RUNTIME_EVENT_JSON")
    if not raw:
        raise PointerGateError("AGENT_RUNTIME_EVENT_JSON is required")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PointerGateError(f"invalid runtime event JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("event_type") != "before.commit":
        raise PointerGateError("submodule pointer gate requires before.commit")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise PointerGateError("before.commit metadata is required")
    entries = metadata.get("staged_entries")
    if not isinstance(entries, list):
        raise PointerGateError("before.commit staged_entries are required")
    return payload


def _staged_submodule_urls(repo_root: Path) -> dict[str, str]:
    result = _run(["git", "show", ":.gitmodules"], cwd=repo_root)
    if result.returncode != 0:
        raise PointerGateError("staged .gitmodules is required for submodule pointers")
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(result.stdout)
    except configparser.Error as exc:
        raise PointerGateError(f"staged .gitmodules is invalid: {exc}") from exc
    urls: dict[str, str] = {}
    for section in parser.sections():
        path = parser.get(section, "path", fallback="").strip()
        url = parser.get(section, "url", fallback="").strip()
        if not path:
            continue
        if not url:
            raise PointerGateError(f"submodule {path} has no configured URL")
        if path in urls:
            raise PointerGateError(f"submodule path is duplicated in .gitmodules: {path}")
        urls[path] = url
    return urls


def _validate_remote_url(path: str, url: str) -> None:
    if url.startswith(("./", "../")):
        raise PointerGateError(
            f"submodule {path} uses a relative URL unsupported by this tracer gate"
        )
    if url.startswith(("ext::", "fd::")):
        raise PointerGateError(f"submodule {path} uses a forbidden remote helper")


def _advertised_oids(repo_root: Path, path: str, url: str) -> set[str]:
    command = ["git"]
    for value in ALLOWED_PROTOCOL_CONFIG:
        command.extend(["-c", value])
    command.extend(["ls-remote", "--refs", url])
    advertised = _run(command, cwd=repo_root)
    if advertised.returncode != 0:
        raise PointerGateError(f"cannot list configured remote refs for submodule {path}")

    oids: set[str] = set()
    for line in advertised.stdout.splitlines():
        fields = line.split()
        if fields and OID_PATTERN.fullmatch(fields[0]):
            oids.add(fields[0].lower())
    return oids


def _fetchable(repo_root: Path, path: str, url: str, oid: str) -> None:
    _validate_remote_url(path, url)
    if oid in _advertised_oids(repo_root, path, url):
        return

    with tempfile.TemporaryDirectory(prefix="agent-submodule-pointer-") as raw:
        bare = Path(raw) / "objects.git"
        initialized = _run(["git", "init", "--bare", "-q", str(bare)], cwd=repo_root)
        if initialized.returncode != 0:
            raise PointerGateError("cannot initialize temporary pointer verification repo")
        command = ["git"]
        for value in ALLOWED_PROTOCOL_CONFIG:
            command.extend(["-c", value])
        command.extend(
            [
                "--git-dir",
                str(bare),
                "fetch",
                "--quiet",
                "--no-tags",
                "--no-write-fetch-head",
                url,
                oid,
            ]
        )
        fetched = _run(command, cwd=repo_root)
        if fetched.returncode != 0:
            raise PointerGateError(
                f"submodule pointer {path}@{oid[:12]} is not fetchable from its configured remote"
            )


def check() -> None:
    payload = _event()
    repo_root = Path(os.environ.get("AGENT_RUNTIME_REPO_ROOT", "")).resolve()
    if not repo_root.is_dir():
        raise PointerGateError("AGENT_RUNTIME_REPO_ROOT is unavailable")
    metadata = payload["metadata"]
    entries = metadata["staged_entries"]
    pointers: list[tuple[str, str]] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            raise PointerGateError("staged entry must be an object")
        if raw_entry.get("mode") != "160000" or not raw_entry.get("present_in_index"):
            continue
        path = raw_entry.get("path")
        oid = raw_entry.get("blob_oid")
        if not isinstance(path, str) or not path:
            raise PointerGateError("staged submodule path is invalid")
        if not isinstance(oid, str) or not OID_PATTERN.fullmatch(oid):
            raise PointerGateError(f"staged submodule OID is invalid: {path}")
        pointers.append((path, oid.lower()))
    if not pointers:
        return
    urls = _staged_submodule_urls(repo_root)
    for path, oid in pointers:
        url = urls.get(path)
        if url is None:
            raise PointerGateError(
                f"staged submodule pointer has no matching .gitmodules entry: {path}"
            )
        _fetchable(repo_root, path, url, oid)


def main() -> int:
    try:
        check()
    except PointerGateError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
