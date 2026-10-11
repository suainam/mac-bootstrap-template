#!/usr/bin/env bash
# package-ownership.sh: Query authoritative package manager ownership.
# Usage:
#   scripts/package-ownership.sh list-zb               # Print all Zerobrew formula names
#   scripts/package-ownership.sh owner <formula>       # Print "zb" or "brew"
#   scripts/package-ownership.sh desired-zb [Brewfile] # Print Zerobrew formulas declared in active Brewfile
#   scripts/package-ownership.sh desired-brew [Brewfile] # Print Homebrew formulas declared in active Brewfile

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="${PACKAGE_OWNERSHIP_MANIFEST:-$DIR/scripts/package-ownership.json}"

list_zb() {
  if [ ! -f "$MANIFEST" ]; then
    echo "Error: package ownership manifest not found at $MANIFEST" >&2
    exit 1
  fi
  if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required to parse $MANIFEST" >&2
    exit 1
  fi
  jq -er '.zerobrew_formulas[]' "$MANIFEST"
}

owner() {
  local target="$1"
  local normalized="$target"

  # Only normalize homebrew/core/<name> or core/<name>; do NOT strip other tap prefixes (e.g. custom/tap/fd stays custom/tap/fd)
  case "$target" in
    homebrew/core/*)
      normalized="${target#homebrew/core/}"
      ;;
    core/*)
      normalized="${target#core/}"
      ;;
  esac

  local zb_formulas
  zb_formulas="$(list_zb)"

  if printf '%s\n' "$zb_formulas" | /usr/bin/grep -Fxq "$normalized"; then
    echo "zb"
  else
    echo "brew"
  fi
}

desired() {
  local target_manager="$1"
  local brewfile="${2:-$DIR/Brewfile}"
  local export_private="${MAC_BOOTSTRAP_PRIVATE_DIR:-$DIR/../private}"
  local export_profile="${MAC_BOOTSTRAP_PROFILE:-$("$DIR/scripts/resolve-profile.sh" 2>/dev/null || echo "work")}"

  export MAC_BOOTSTRAP_PRIVATE_DIR="$export_private"
  export MAC_BOOTSTRAP_PROFILE="$export_profile"
  export HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR="$export_private"
  export HOMEBREW_MAC_BOOTSTRAP_PROFILE="$export_profile"

  local tmp_list
  tmp_list="$(mktemp)"
  trap 'rm -f "$tmp_list"' RETURN

  brew bundle list --file="$brewfile" --formula > "$tmp_list"

  while IFS= read -r formula; do
    [ -n "$formula" ] || continue
    local pkg_owner
    pkg_owner="$(owner "$formula")"
    if [ "$target_manager" = "$pkg_owner" ]; then
      echo "$formula"
    fi
  done < "$tmp_list"
}

case "${1:-}" in
  list-zb)
    list_zb
    ;;
  owner)
    [ -n "${2:-}" ] || { echo "Usage: $0 owner <formula>" >&2; exit 2; }
    owner "$2"
    ;;
  desired-zb)
    desired "zb" "${2:-}"
    ;;
  desired-brew)
    desired "brew" "${2:-}"
    ;;
  *)
    echo "Usage: $0 {list-zb|owner <formula>|desired-zb [Brewfile]|desired-brew [Brewfile]}" >&2
    exit 2
    ;;
esac
