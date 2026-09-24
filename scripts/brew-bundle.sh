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
PRIVATE_DIR=""
if [ -n "${MAC_BOOTSTRAP_PRIVATE_DIR:-}" ] && [ -d "$MAC_BOOTSTRAP_PRIVATE_DIR" ]; then
  PRIVATE_DIR="$MAC_BOOTSTRAP_PRIVATE_DIR"
elif [ -d "$DIR/../private" ]; then
  PRIVATE_DIR="$(cd "$DIR/../private" && pwd)"
fi

if [ -z "${MAC_BOOTSTRAP_PROFILE:-}" ] && [ -x "$DIR/resolve-profile.sh" ]; then
  PROFILE="$("$DIR/resolve-profile.sh" 2>/dev/null || true)"
else
  PROFILE="${MAC_BOOTSTRAP_PROFILE:-}"
fi
if [ -z "$PROFILE" ] && [ -n "$PRIVATE_DIR" ]; then
  if [ -f "$PRIVATE_DIR/current_profile" ]; then
    PROFILE="$(tr -d '[:space:]' < "$PRIVATE_DIR/current_profile")"
  elif [ -f "$PRIVATE_DIR/profile" ]; then
    PROFILE="$(tr -d '[:space:]' < "$PRIVATE_DIR/profile")"
  fi
fi

BREW_SKIP="${MAC_BOOTSTRAP_BREW_SKIP:-}"

load_skip_file() {
  local file="$1"
  [ -f "$file" ] || return 0
  while IFS= read -r skip_line || [ -n "$skip_line" ]; do
    case "$skip_line" in
      ''|'#'*) continue ;;
    esac
    BREW_SKIP="$BREW_SKIP ${skip_line%%#*}"
  done < "$file"
}

if [ -n "$PRIVATE_DIR" ]; then
  # 1. Base private/brew.skip (common to all profiles)
  load_skip_file "$PRIVATE_DIR/brew.skip"
  # 2. Profile-specific skip file (e.g. private/profiles/home/brew.skip or private/brew.home.skip)
  if [ -n "$PROFILE" ]; then
    load_skip_file "$PRIVATE_DIR/profiles/$PROFILE/brew.skip"
    load_skip_file "$PRIVATE_DIR/brew.$PROFILE.skip"
  fi
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
