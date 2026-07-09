#!/usr/bin/env bash
set -euo pipefail

# Install global npm packages from agent/npm-global-packages.txt.
# Usage:
#   ./scripts/install-npm-global-packages.sh          # install missing packages
#   ./scripts/install-npm-global-packages.sh --yes    # skip confirmation
#   ./scripts/install-npm-global-packages.sh --upgrade # upgrade all listed packages
#   make npm-packages

ASSUME_YES=0
UPGRADE=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    -y|--yes) ASSUME_YES=1 ;;
    --upgrade) UPGRADE=1 ;;
    -h|--help)
      echo "Usage: install-npm-global-packages.sh [--yes] [--upgrade]"
      exit 0 ;;
    *) echo "Unknown: $1" >&2; exit 2 ;;
  esac
  shift
done

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGES_FILE="$DIR/agent/npm-global-packages.txt"

if [ ! -f "$PACKAGES_FILE" ]; then
  echo "ERROR: $PACKAGES_FILE not found" >&2
  exit 1
fi

PACKAGES=()
while IFS= read -r package; do
  PACKAGES+=("$package")
done < <(grep -vE '^\s*(#|$)' "$PACKAGES_FILE")

if [ "${#PACKAGES[@]}" -eq 0 ]; then
  echo "No packages defined in $PACKAGES_FILE"
  exit 0
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm not installed. Install Node first (for example: brew install node)." >&2
  exit 1
fi

if [ "$ASSUME_YES" -eq 0 ]; then
  if [ "$UPGRADE" -eq 1 ]; then
    echo "The following global npm packages will be upgraded:"
  else
    echo "The following global npm packages will be ensured:"
  fi
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

installed_json="$(npm -g ls --depth=0 --json 2>/dev/null || true)"
if [ -z "$installed_json" ]; then
  installed_json='{}'
fi
installed_names="$(printf '%s' "$installed_json" | node -e 'const fs=require("fs"); const data=JSON.parse(fs.readFileSync(0,"utf8")||"{}"); for (const name of Object.keys(data.dependencies||{})) console.log(name);')"

for pkg in "${PACKAGES[@]}"; do
  pkg_name="$pkg"
  if [ "$UPGRADE" -eq 1 ]; then
    echo "  UPGRADE: $pkg"
    npm install -g "$pkg"
  elif printf '%s\n' "$installed_names" | grep -Fxq "$pkg_name"; then
    echo "  SKIP: $pkg already installed"
  else
    echo "  INSTALL: $pkg"
    npm install -g "$pkg"
  fi
done

echo "=== Done. npm global packages reconciled. ==="
