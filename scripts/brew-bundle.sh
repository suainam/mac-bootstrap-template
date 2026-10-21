#!/usr/bin/env bash
# brew-bundle.sh: Reconcile packages according to active Brewfile.
# Usage:
#   scripts/brew-bundle.sh [install]      Normal reconcile / install via Homebrew
#   scripts/brew-bundle.sh migrate        Migrate any legacy Zerobrew packages to Homebrew

set -euo pipefail

MODE="install"
if [ "$#" -gt 0 ]; then
  case "$1" in
    install)
      MODE="install"
      ;;
    migrate)
      MODE="migrate"
      ;;
    *)
      echo "Usage: $0 [install|migrate]" >&2
      exit 2
      ;;
  esac
fi

DIR="$(cd "$(dirname "$0")/.." && pwd)"
export MAC_BOOTSTRAP_PRIVATE_DIR="${MAC_BOOTSTRAP_PRIVATE_DIR:-$DIR/../private}"
export MAC_BOOTSTRAP_PROFILE="${MAC_BOOTSTRAP_PROFILE:-$("$DIR/scripts/resolve-profile.sh" 2>/dev/null || echo "work")}"

# Homebrew 7 filters env in Ruby runtime; export HOMEBREW_* variables for safe transport.
export HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR="$MAC_BOOTSTRAP_PRIVATE_DIR"
export HOMEBREW_MAC_BOOTSTRAP_PROFILE="$MAC_BOOTSTRAP_PROFILE"

if [ "$MODE" = "migrate" ]; then
  exec "$DIR/scripts/migrate-to-homebrew.sh"
fi

# Keep manually installed GUI apps outside Homebrew ownership.
for entry in 'microsoft-edge:Microsoft Edge.app' 'zed:Zed.app' 'clash-verge-rev:Clash Verge.app' 'grok-bot:Grok Bot.app'; do
  token="${entry%%:*}"
  app="${entry#*:}"
  if ! brew list --cask "$token" >/dev/null 2>&1 && { [ -d "/Applications/$app" ] || [ -d "$HOME/Applications/$app" ]; }; then
    export HOMEBREW_BUNDLE_CASK_SKIP="${HOMEBREW_BUNDLE_CASK_SKIP:-} $token"
  fi
done

brew bundle install --no-upgrade --file="$DIR/Brewfile"
exit 0
