#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$DIR/.venv/bin/python}"
BREWFILE="$DIR/Brewfile"
MANIFEST="$DIR/scripts/doctor-manifest.json"

for arg in "$@"; do
  case "$arg" in
    --strict)
      ;;
    -h|--help)
      echo "Usage: scripts/doctor.sh [--strict]"
      exit 0
      ;;
    *)
      echo "Usage: scripts/doctor.sh [--strict]" >&2
      exit 2
      ;;
  esac
done

PRIVATE_DIR=""
if [ -n "${MAC_BOOTSTRAP_PRIVATE_DIR:-}" ] && [ -d "$MAC_BOOTSTRAP_PRIVATE_DIR" ]; then
  PRIVATE_DIR="$(cd "$MAC_BOOTSTRAP_PRIVATE_DIR" && pwd)"
elif [ -d "$DIR/../private" ]; then
  PRIVATE_DIR="$(cd "$DIR/../private" && pwd)"
fi

PROFILE="${MAC_BOOTSTRAP_PROFILE:-}"
if [ -z "$PROFILE" ]; then
  if [ -x "$DIR/scripts/resolve-profile.sh" ]; then
    PROFILE="$(MAC_BOOTSTRAP_PRIVATE_DIR="$PRIVATE_DIR" "$DIR/scripts/resolve-profile.sh" 2>/dev/null || true)"
  elif [ -x "$DIR/resolve-profile.sh" ]; then
    PROFILE="$(MAC_BOOTSTRAP_PRIVATE_DIR="$PRIVATE_DIR" "$DIR/resolve-profile.sh" 2>/dev/null || true)"
  fi
fi

export MAC_BOOTSTRAP_PRIVATE_DIR="$PRIVATE_DIR"
export MAC_BOOTSTRAP_PROFILE="$PROFILE"
export HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR="$PRIVATE_DIR"
export HOMEBREW_MAC_BOOTSTRAP_PROFILE="$PROFILE"

if [ ! -x "$PYTHON" ]; then
  echo "Missing project Python: $PYTHON" >&2
  exit 2
fi

"$PYTHON" "$DIR/scripts/run-doctor-checks.py" "$BREWFILE" "$MANIFEST" "$@"
