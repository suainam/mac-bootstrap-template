#!/usr/bin/env python3
"""Rescue and guard the ai-memory offline spool.

Why this exists
---------------
The OMP capture extension bakes the endpoint into each spool entry at write
time (`{data_dir}/hook-spool/*.json` -> `{"url": "http://host:port/hook?..."}`)
and, when draining, treats any non-retryable 4xx as "permanently rejected" and
deletes the file. A session that started before a `--server-url` change keeps
writing entries for the OLD endpoint. If anything later answers on that old
address with a 4xx, the drain silently destroys the whole backlog.

That happened once (2026-10-22): 47 events from a live session were deleted by
a temporary local server answering 401 for a token it did not own.

This tool rewrites every entry to the canonical endpoint, then delivers it.
Delivery is idempotent because the extension mints an `ingest_key` at spool
time and bakes it into the URL query, so a double drain cannot duplicate.

Invariants
----------
* Never delete on a 4xx. A rejected event is kept and reported; only a 2xx
  response consumes an entry. Losing memory is worse than a growing backlog.
* Rewrite is atomic (tmp + rename), so a concurrently draining extension never
  reads a torn file.
* `--dry-run` is read-only and is what `make memory-check` uses to fail loudly.

Usage
-----
    ai-memory-spool-forward.py [--dry-run] [--json] [--quiet]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse as up
from pathlib import Path
from typing import Any

# The shared primary lives on a private address, so no default endpoint is baked
# in: this file ships in the public template. Resolution order is
# $AI_MEMORY_SERVER_URL, then the 0600 env file owned by the private overlay.
DEFAULT_PROXY = "http://127.0.0.1:7897"
PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
NO_PROXY_VARS = ("NO_PROXY", "no_proxy")
PRIVATE_ENV = Path("~/.omp/agent/.env").expanduser()


def private_env_value(key: str) -> str | None:
    try:
        text = PRIVATE_ENV.read_text(errors="ignore")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :]
        if not line.startswith(f"{key}="):
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value or None
    return None


def canonical_server() -> str:
    for candidate in (os.environ.get("AI_MEMORY_SERVER_URL"), private_env_value("AI_MEMORY_SERVER_URL")):
        if candidate and candidate.strip():
            return candidate.strip().rstrip("/")
    raise SystemExit(
        "ai-memory spool: no server URL configured; set AI_MEMORY_SERVER_URL "
        "or add it to the private ~/.omp/agent/.env (see docs/ai-memory-shared-primary.md)"
    )


def proxy_url() -> str | None:
    for var in PROXY_VARS:
        value = os.environ.get(var)
        if value:
            return value
    return DEFAULT_PROXY


def spool_dirs(explicit: list[str]) -> list[Path]:
    """Resolve candidate hook-spool directories.

    Each candidate is a DATA dir; the spool lives in its `hook-spool` child.
    An explicit path is accepted as either form so a caller can point at the
    spool itself, but a data dir is what gets joined here.
    """
    if explicit:
        candidates = [Path(d).expanduser() for d in explicit]
    else:
        candidates = []
        env = os.environ.get("AI_MEMORY_DATA_DIR", "").strip()
        if env:
            candidates.append(Path(env).expanduser())
        candidates.append(Path.home() / ".omp" / "agent" / "ai-memory-cc15")
        if sys.platform == "darwin":
            candidates.append(Path.home() / "Library" / "Application Support" / "ai-memory")
        else:
            candidates.append(
                Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "ai-memory"
            )
    seen: set[Path] = set()
    out: list[Path] = []
    for d in candidates:
        spool = d if d.name == "hook-spool" else d / "hook-spool"
        if spool in seen:
            continue
        seen.add(spool)
        if spool.is_dir():
            out.append(spool)
    return out


def retarget(entry: dict[str, Any], server: str) -> tuple[dict[str, Any], bool]:
    raw = entry.get("url")
    if not isinstance(raw, str) or not raw:
        return entry, False
    parts = up.urlsplit(raw)
    want = up.urlsplit(server)
    if parts.scheme == want.scheme and parts.netloc == want.netloc:
        return entry, False
    fixed = up.urlunsplit((want.scheme, want.netloc, parts.path, parts.query, ""))
    return {**entry, "url": fixed}, True


def deliver(entry: dict[str, Any], proxy: str | None) -> int:
    """POST one spool entry. Returns the HTTP status, or 0 when unreachable."""
    url = entry.get("url")
    body = entry.get("body")
    if not isinstance(url, str) or not isinstance(body, str):
        return -1
    cmd = ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "-m", "20"]
    if proxy:
        cmd += ["-x", proxy]
    for var in NO_PROXY_VARS:
        if os.environ.get(var):
            cmd += ["--noproxy", os.environ[var]]
            break
    cmd += ["-H", "Content-Type: application/json", "-H", "X-AI-Memory-Client: spool-forward"]
    bearer = entry.get("token")
    if bearer:
        cmd += ["-H", f"Authorization: Bearer {bearer}"]
    cmd += ["--data-binary", "@-", url]
    try:
        proc = subprocess.run(cmd, input=body.encode(), capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return 0
    out = proc.stdout.decode(errors="replace").strip()
    return int(out) if out.isdigit() else 0


def write_atomic(path: Path, entry: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(entry, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description="Rewrite and deliver ai-memory spool entries to the canonical endpoint.")
    ap.add_argument("--data-dir", action="append", default=[], help="data dir whose hook-spool to process (repeatable)")
    ap.add_argument("--server", default=None, help="canonical endpoint (default: $AI_MEMORY_SERVER_URL, else the private env file)")
    ap.add_argument("--dry-run", action="store_true", help="report only; rewrite and deliver nothing")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--quiet", action="store_true", help="suppress the human summary")
    args = ap.parse_args()

    server = (args.server or canonical_server()).rstrip("/")
    proxy = proxy_url()
    dirs = spool_dirs(args.data_dir)

    stale = delivered = kept = unreachable = 0
    for spool in dirs:
        for name in sorted(glob.glob(str(spool / "*.json"))):
            path = Path(name)
            try:
                entry = json.loads(path.read_text())
            except (OSError, ValueError):
                continue  # torn or foreign file; leave it alone
            if not isinstance(entry, dict):
                continue
            entry, was_stale = retarget(entry, server)
            if was_stale:
                stale += 1
                if not args.dry_run:
                    write_atomic(path, entry)
            if args.dry_run:
                continue
            status = deliver(entry, proxy)
            if 200 <= status < 300:
                try:
                    path.unlink()
                except OSError:
                    pass
                delivered += 1
            elif status == 0:
                unreachable += 1
            else:
                kept += 1  # includes 4xx on purpose: never drop on rejection

    remaining = sum(len(glob.glob(str(d / "*.json"))) for d in dirs)
    report = {
        "server": server,
        "spool_dirs": [str(d) for d in dirs],
        "stale_entries": stale,
        "delivered": delivered,
        "kept_after_rejection": kept,
        "unreachable": unreachable,
        "remaining": remaining,
        "dry_run": args.dry_run,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    elif not args.quiet:
        print(f"spool  server={server}")
        for d in dirs:
            print(f"  dir    {d}")
        if args.dry_run:
            print(f"  stale  {stale} entr{'y' if stale == 1 else 'ies'} point at a non-canonical endpoint")
            print(f"  total  {remaining} queued")
        else:
            print(f"  retargeted {stale}, delivered {delivered}, kept {kept}, unreachable {unreachable}")
            print(f"  total  {remaining} queued")

    if args.dry_run:
        return 1 if (stale or remaining) else 0
    return 1 if remaining else 0


if __name__ == "__main__":
    sys.exit(main())
