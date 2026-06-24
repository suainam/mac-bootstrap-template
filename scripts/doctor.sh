#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$DIR/.venv/bin/python}"
BREWFILE="$DIR/Brewfile"
MANIFEST="$DIR/scripts/doctor-manifest.json"

if [ ! -x "$PYTHON" ]; then
  echo "Missing project Python: $PYTHON" >&2
  exit 2
fi

"$PYTHON" "$DIR/scripts/run-doctor-checks.py" "$BREWFILE" "$MANIFEST"
