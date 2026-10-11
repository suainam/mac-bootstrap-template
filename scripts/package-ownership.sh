#!/usr/bin/env bash
# package-ownership.sh: Query authoritative package manager ownership.
# Usage:
#   scripts/package-ownership.sh list-zb               # Print all Zerobrew formula names (from declaration)
#   scripts/package-ownership.sh owner <formula>       # Print "zb" or "brew"
#   scripts/package-ownership.sh desired-zb [Brewfile] # Print Zerobrew formulas declared in active Brewfile
#   scripts/package-ownership.sh desired-brew [Brewfile] # Print Homebrew formulas declared in active Brewfile

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="${PACKAGE_OWNERSHIP_MANIFEST:-$DIR/scripts/package-ownership.json}"

list_zb() {
  if [ -f "$MANIFEST" ]; then
    if command -v jq >/dev/null 2>&1; then
      jq -r '.zerobrew_formulas[]' "$MANIFEST"
    else
      /usr/bin/sed -n 's/^[[:space:]]*"\([a-zA-Z0-9_@-]*\)",\{0,1\}[[:space:]]*$/\1/p' "$MANIFEST"
    fi
  else
    # Fallback to hardcoded list if manifest is missing
    cat << 'EOF'
age
ast-grep
docker
docker-buildx
docker-compose
fd
fzf
gh
gitleaks
herdr
lazygit
pngpaste
rclone
rtk
rustic
sops
tree
tree-sitter-cli
uv
yazi
zoxide
EOF
  fi
}

is_zb() {
  local target="$1"
  local formula
  while IFS= read -r formula; do
    if [ "$formula" = "$target" ]; then
      return 0
    fi
  done < <(list_zb)
  return 1
}

owner() {
  local target="$1"
  # Short name stripping tap prefix if present
  local short_name="${target##*/}"
  if is_zb "$short_name" || is_zb "$target"; then
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
    if [ "$pkg_owner" = "$target_manager" ]; then
      echo "$formula"
    fi
  done < "$tmp_list"
}

case "${1:-}" in
  list-zb)
    list_zb
    ;;
  owner)
    if [ -z "${2:-}" ]; then
      echo "Usage: $0 owner <formula>" >&2
      exit 2
    fi
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
