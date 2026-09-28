#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$DIR/.venv/bin/python}"
BREWFILE="$DIR/Brewfile"
MANIFEST="$DIR/scripts/doctor-manifest.json"

PRIVATE_DIR=""
if [ -n "${MAC_BOOTSTRAP_PRIVATE_DIR:-}" ] && [ -d "$MAC_BOOTSTRAP_PRIVATE_DIR" ]; then
  PRIVATE_DIR="$MAC_BOOTSTRAP_PRIVATE_DIR"
elif [ -d "$DIR/../private" ]; then
  PRIVATE_DIR="$(cd "$DIR/../private" && pwd)"
fi

PROFILE=""
if [ -z "${MAC_BOOTSTRAP_PROFILE:-}" ]; then
  if [ -x "$DIR/scripts/resolve-profile.sh" ]; then
    PROFILE="$("$DIR/scripts/resolve-profile.sh" 2>/dev/null || true)"
  elif [ -x "$DIR/resolve-profile.sh" ]; then
    PROFILE="$("$DIR/resolve-profile.sh" 2>/dev/null || true)"
  fi
else
  PROFILE="${MAC_BOOTSTRAP_PROFILE:-}"
fi

EXTRA_BREWFILES=()
if [ -n "$PRIVATE_DIR" ] && [ -n "$PROFILE" ]; then
  if [ -f "$PRIVATE_DIR/profiles/$PROFILE/Brewfile" ]; then
    EXTRA_BREWFILES+=("$PRIVATE_DIR/profiles/$PROFILE/Brewfile")
  fi
  if [ -f "$PRIVATE_DIR/profiles/$PROFILE/Brewfile.experimental" ]; then
    EXTRA_BREWFILES+=("$PRIVATE_DIR/profiles/$PROFILE/Brewfile.experimental")
  fi
fi

if [ ! -x "$PYTHON" ]; then
  echo "Missing project Python: $PYTHON" >&2
  exit 2
fi

"$PYTHON" "$DIR/scripts/run-doctor-checks.py" "$BREWFILE" "$MANIFEST" ${EXTRA_BREWFILES[@]+"${EXTRA_BREWFILES[@]}"}
