#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST=""
INIT_GIT=0

usage() {
  cat <<'EOF'
Usage: scripts/export-public-template.sh --dest DIR [options]

Copies public template files into DIR without git history. Applies .publicignore.

Options:
  --dest DIR   Destination directory.
  --init-git   Run git init and git add in the destination.
  -h, --help   Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dest)
      DEST="${2:?Missing value for --dest}"
      shift
      ;;
    --init-git)
      INIT_GIT=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [ -z "$DEST" ]; then
  usage >&2
  exit 2
fi

cd "$DIR"
./scripts/privacy-audit.sh

if [ -e "$DEST" ]; then
  if [ -n "$(find "$DEST" -mindepth 1 -maxdepth 1 2>/dev/null || true)" ]; then
    echo "ERROR: destination exists and is not empty: $DEST" >&2
    echo "Choose a new empty directory to avoid stale private files." >&2
    exit 1
  fi
fi

mkdir -p "$DEST"

python3 - "$DEST" <<'PY'
from __future__ import annotations

import shutil
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

dest = Path(sys.argv[1]).resolve()


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


def ignored_for_public(path: str, patterns: list[str]) -> bool:
    normalized = path.lstrip("./")
    for pattern in patterns:
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


patterns = public_ignore_patterns()
files = subprocess.check_output(
    ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
).decode().split("\0")
for rel in filter(None, files):
    if ignored_for_public(rel, patterns):
        continue
    src = Path(rel)
    if not src.exists() or src.is_dir():
        continue
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
PY

if [ "$INIT_GIT" -eq 1 ]; then
  git -C "$DEST" init
  git -C "$DEST" add .
fi

echo "Exported public template files to: $DEST"
