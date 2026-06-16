#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
BREWFILE="$DIR/Brewfile"
MANIFEST="$DIR/scripts/doctor-manifest.json"

python3 "$DIR/scripts/run-doctor-checks.py" "$BREWFILE" "$MANIFEST"
