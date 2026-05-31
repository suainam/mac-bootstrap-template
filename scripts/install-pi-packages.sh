#!/usr/bin/env bash
set -euo pipefail

# ─── Install Pi terminal agent packages ─────────────────────────────────────
# Package list source: agent/pi-packages.txt (single source of truth).
# Scripts that manage Pi packages should read from that file, not hardcode.
#
# Usage:
#   ./scripts/install-pi-packages.sh          # interactive
#   ./scripts/install-pi-packages.sh --yes    # assume yes to all prompts
#   make pi-packages                          # alias via Makefile
# ──────────────────────────────────────────────────────────────────────────────

ASSUME_YES=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help)
      echo "Usage: install-pi-packages.sh [--yes]"
      exit 0 ;;
    *) echo "Unknown: $1" >&2; exit 2 ;;
  esac
  shift
done

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGES_FILE="$DIR/agent/pi-packages.txt"

if [ ! -f "$PACKAGES_FILE" ]; then
  echo "ERROR: $PACKAGES_FILE not found" >&2
  exit 1
fi

# Read non-empty, non-comment lines
PACKAGES=()
while IFS= read -r package; do
  PACKAGES+=("$package")
done < <(grep -vE '^\s*(#|$)' "$PACKAGES_FILE")

if [ "${#PACKAGES[@]}" -eq 0 ]; then
  echo "No packages defined in $PACKAGES_FILE"
  exit 0
fi

if ! command -v pi >/dev/null 2>&1; then
  echo "ERROR: pi not installed. Run 'make bootstrap' first." >&2
  exit 1
fi

if [ "$ASSUME_YES" -eq 0 ]; then
  echo "The following Pi packages will be installed:"
  for pkg in "${PACKAGES[@]}"; do
    echo "  - $pkg"
  done
  echo "Proceed? [y/N]"
  read -r confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
  fi
fi

INSTALLED=$(pi list 2>/dev/null || true)

for pkg in "${PACKAGES[@]}"; do
  pkg_name="${pkg#npm:}"
  if echo "$INSTALLED" | grep -q "$pkg_name"; then
    echo "  SKIP: $pkg already installed"
  else
    echo "  INSTALL: $pkg"
    pi install "$pkg"
  fi
done

echo "=== Done. Pi packages installed. ==="
