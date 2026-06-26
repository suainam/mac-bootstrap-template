#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
HISTORY=0
WARN_ONLY=0

usage() {
  cat <<'EOF'
Usage: scripts/privacy-audit.sh [options]

Redacted scan for secrets and personal markers. Values are never printed.
Default scan covers the public export view: tracked/unignored files minus
patterns in .publicignore.

Options:
  --history    Scan all git blobs in history.
  --warn-only  Always exit 0.
  -h, --help   Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --history) HISTORY=1 ;;
    --warn-only) WARN_ONLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

cd "$DIR"

python3 - "$HISTORY" "$WARN_ONLY" <<'PY'
from __future__ import annotations

import math
import os
import re
import subprocess
import sys
from pathlib import Path
from collections import Counter
from fnmatch import fnmatch

history = sys.argv[1] == "1"
warn_only = sys.argv[2] == "1"

secret_literals = [
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("huggingface_token", re.compile(r"\bhf_[0-9A-Za-z]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("url_with_credentials", re.compile(r"[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@")),
]

assignment = re.compile(
    r"""(?ix)
    ^\s*(?:export\s+|local\s+)?
    \b(api[_-]?key|token|secret|password|passwd|pwd|access[_-]?key|private[_-]?key|client[_-]?secret)\b
    \s*[:=]\s*
    (?P<value>.+?)
    \s*(?:[#;].*)?$
    """
)

url_assignment = re.compile(
    r"""(?ix)
    ^\s*(url|subscription|subscribe_url|provider_url)\s*:\s*
    ["']?(?P<url>https?://[^"'\s]+)
    """
)

home_path_pattern = "/" + "Users/" + r"""[^/\s:'"`]+"""

personal_markers = [
    ("absolute_home_path", re.compile(home_path_pattern)),
    ("hardcoded_owner_name", re.compile(r"\b" + "su" + "ai" + r"\b", re.I)),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
]

allowed_email_domains = {"example.com", "example.org", "example.net"}
allowed_url_hosts = {
    "www.gstatic.com",
    "testingcf.jsdelivr.net",
    "cdn.jsdelivr.net",
    "github.com",
    "raw.githubusercontent.com",
}
allowed_path_prefixes = ("private.example/",)
skip_suffixes = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".sqlite", ".db")
skip_exact_names = {"package-lock.json"}


def public_ignore_patterns() -> list[str]:
    path = Path(".publicignore")
    if not path.exists():
        return []
    patterns = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


PUBLIC_IGNORE = public_ignore_patterns()


def ignored_for_public(path: str) -> bool:
    normalized = path.lstrip("./")
    for pattern in PUBLIC_IGNORE:
        pat = pattern.lstrip("./")
        if pat.endswith("/"):
            prefix = pat.rstrip("/") + "/"
            if normalized.startswith(prefix):
                return True
            continue
        if "/" not in pat and fnmatch(Path(normalized).name, pat):
            return True
        if fnmatch(normalized, pat):
            return True
    return False


def entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {ch: value.count(ch) for ch in set(value)}
    return -sum((n / len(value)) * math.log2(n / len(value)) for n in counts.values())


def clean_value(raw: str) -> str:
    value = raw.strip().strip(",")
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.strip()


def is_placeholder(value: str) -> bool:
    lowered = value.lower()
    placeholder_bits = (
        "example",
        "placeholder",
        "your_",
        "your-",
        "xxx",
        "<",
        "{{",
        "}}",
        "$",
        "os.environ",
        "process.env",
        "getenv",
        "no-auth-required",
        "line#",
        "line%",
        "user>:<pass",
    )
    return (
        not value
        or any(bit in lowered for bit in placeholder_bits)
        or lowered in {"none", "null", "true", "false"}
    )


def assignment_finding(line: str) -> str | None:
    match = assignment.search(line)
    if not match:
        return None
    value = clean_value(match.group("value"))
    if (
        value.startswith(("{", "["))
        or value.startswith("z.")
        or "z.string(" in value
        or "writeOnly" in value
        or "readOnly" in value
        or " || " in value
    ):
        return None
    if is_placeholder(value):
        return None
    if len(value) >= 12 and entropy(value) >= 3.0:
        return "secret_assignment"
    return None


def url_finding(line: str) -> str | None:
    match = url_assignment.search(line)
    if not match:
        return None
    value = match.group("url")
    if is_placeholder(value):
        return None
    host = value.split("://", 1)[1].split("/", 1)[0].split("@")[-1].split(":")[0].lower()
    if host in allowed_url_hosts:
        return None
    return "sensitive_url"


def scan_text(path: str, text: str, origin: str) -> list[tuple[str, str, str, int]]:
    findings = []
    if (
        path.startswith(allowed_path_prefixes)
        or path.endswith(skip_suffixes)
        or Path(path).name in skip_exact_names
    ):
        return findings
    for line_no, line in enumerate(text.splitlines(), 1):
        for category, pattern in secret_literals:
            if pattern.search(line):
                if category == "url_with_credentials" and any(token in line for token in ("<user>", "<pass>", "&lt;user&gt;", "&lt;pass&gt;")):
                    continue
                findings.append((origin, "SECRET", category, line_no))
        category = assignment_finding(line)
        if category:
            findings.append((origin, "SECRET", category, line_no))
        category = url_finding(line)
        if category:
            findings.append((origin, "SECRET", category, line_no))
        for category, pattern in personal_markers:
            for match in pattern.finditer(line):
                if category == "email":
                    email = match.group(0).lower()
                    if email == "git@github.com":
                        continue
                    if email.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".icns")):
                        continue
                    domain = email.rsplit("@", 1)[-1]
                    if domain in allowed_email_domains:
                        continue
                findings.append((origin, "PERSONAL", category, line_no))
    return findings


def public_files() -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    return [p for p in raw.decode().split("\0") if p and not ignored_for_public(p)]


def scan_current() -> list[tuple[str, str, str, int]]:
    findings = []
    for path in public_files():
        p = Path(path)
        if not p.exists() or p.is_dir():
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue
        text = data.decode("utf-8", errors="ignore")
        findings.extend(scan_text(path, text, path))
    return findings


def scan_history() -> list[tuple[str, str, str, int]]:
    revs = subprocess.check_output(["git", "rev-list", "--objects", "--all"], text=True)
    seen = set()
    findings = []
    for row in revs.splitlines():
        parts = row.split(maxsplit=1)
        sha = parts[0]
        path = parts[1] if len(parts) == 2 else sha
        if sha in seen or path.endswith(skip_suffixes):
            continue
        seen.add(sha)
        try:
            size = int(subprocess.check_output(["git", "cat-file", "-s", sha], text=True).strip())
        except subprocess.CalledProcessError:
            continue
        if size > 1_000_000:
            continue
        try:
            data = subprocess.check_output(["git", "cat-file", "-p", sha])
        except subprocess.CalledProcessError:
            continue
        if b"\0" in data[:4096]:
            continue
        text = data.decode("utf-8", errors="ignore")
        origin = f"{sha[:12]}:{path}"
        findings.extend(scan_text(path, text, origin))
    return findings


findings = scan_history() if history else scan_current()
unique = []
seen_rows = set()
for row in findings:
    if row not in seen_rows:
        seen_rows.add(row)
        unique.append(row)

label = "history" if history else "public files"
if not unique:
    print(f"privacy-audit: ok ({label}, values suppressed)")
    sys.exit(0)

print(f"privacy-audit: found {len(unique)} issue(s) in {label}; values suppressed")
for (severity, category), count in Counter((row[1], row[2]) for row in unique).most_common():
    print(f"SUMMARY\t{severity}\t{category}\t{count}")

limit = 100
for origin, severity, category, line_no in unique[:limit]:
    print(f"{severity}\t{origin}:{line_no}\t{category}")
if len(unique) > limit:
    print(f"... truncated {len(unique) - limit} more")

if warn_only:
    sys.exit(0)
sys.exit(1)
PY
