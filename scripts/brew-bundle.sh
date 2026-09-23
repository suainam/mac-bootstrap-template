#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -gt 0 ] && [ "$1" != "install" ]; then
  echo "Usage: $0 [install]" >&2
  exit 2
fi

DIR="$(cd "$(dirname "$0")/.." && pwd)"
BREWFILE="$DIR/Brewfile"
TMP_BREWFILE="$(mktemp)"

# Private skip list: space-separated tokens in $MAC_BOOTSTRAP_BREW_SKIP plus
# one token per line in $PRIVATE_SKIP_FILE ("#"-comments and blanks ignored).
# Lets a machine opt out of Brewfile entries (e.g. home vs. work) without
# forking the public Brewfile.
PRIVATE_SKIP_FILE=""
if [ -n "${MAC_BOOTSTRAP_PRIVATE_DIR:-}" ] && [ -f "$MAC_BOOTSTRAP_PRIVATE_DIR/brew.skip" ]; then
  PRIVATE_SKIP_FILE="$MAC_BOOTSTRAP_PRIVATE_DIR/brew.skip"
elif [ -f "$DIR/../private/brew.skip" ]; then
  PRIVATE_SKIP_FILE="$DIR/../private/brew.skip"
fi

BREW_SKIP="${MAC_BOOTSTRAP_BREW_SKIP:-}"
if [ -n "$PRIVATE_SKIP_FILE" ]; then
  while IFS= read -r skip_line || [ -n "$skip_line" ]; do
    case "$skip_line" in
      ''|'#'*) continue ;;
    esac
    BREW_SKIP="$BREW_SKIP ${skip_line%%#*}"
  done < "$PRIVATE_SKIP_FILE"
fi

is_skipped() {
  local token="$1"
  case " $BREW_SKIP " in
    *" $token "*) return 0 ;;
  esac
  return 1
}

cleanup() {
  rm -f "$TMP_BREWFILE"
}
trap cleanup EXIT

has_cask() {
  brew list --cask "$1" >/dev/null 2>&1
}

has_app() {
  [ -d "/Applications/$1" ] || [ -d "$HOME/Applications/$1" ]
}

should_skip_manual_cask() {
  case "$1" in
    microsoft-edge)
      has_cask "$1" || has_app "Microsoft Edge.app"
      ;;
    zed)
      has_cask "$1" || has_app "Zed.app"
      ;;
    clash-verge-rev)
      has_cask "$1" || has_app "Clash Verge.app"
      ;;
    *)
      return 1
      ;;
  esac
}

while IFS= read -r line; do
  case "$line" in
    brew\ \"*\"|cask\ \"*\"|npm\ \"*\")
      token="${line#*\"}"
      token="${token%\"*}"
      if is_skipped "$token"; then
        echo "Skip $token: in private brew skip list."
        continue
      fi
      ;;
  esac
  case "$line" in
    cask\ \"*\")
      token="${line#cask \"}"
      token="${token%\"}"
      if should_skip_manual_cask "$token"; then
        echo "Skip $token: app already exists outside Homebrew."
        continue
      fi
      ;;
  esac
  printf '%s\n' "$line" >> "$TMP_BREWFILE"
done < "$BREWFILE"

brew bundle --file="$TMP_BREWFILE"
