#!/usr/bin/env bash
set -e

if [ "$#" -gt 0 ] && [ "$1" != "install" ]; then
  echo "Usage: $0 [install]" >&2
  exit 2
fi

DIR="$(cd "$(dirname "$0")/.." && pwd)"
BREWFILE="$DIR/Brewfile"
TMP_BREWFILE="$(mktemp)"

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
    visual-studio-code)
      has_cask "$1" || has_app "Visual Studio Code.app"
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
