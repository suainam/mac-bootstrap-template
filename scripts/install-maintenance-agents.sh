#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
ACTION="${1:-install}"
SELECTION="${2:-all}"

case "$ACTION" in
  install|unload) ;;
  *) echo "Usage: $0 [install|unload] [all|claude-daemon|cache-cleanup|downloads-organizer|system-patrol]" >&2; exit 2 ;;
esac

case "$SELECTION" in
  all)
    LABELS=(claude-daemon cache-cleanup downloads-organizer system-patrol)
    ;;
  claude-daemon|cache-cleanup|downloads-organizer|system-patrol)
    LABELS=("$SELECTION")
    ;;
  *) echo "Unknown maintenance agent: $SELECTION" >&2; exit 2 ;;
esac

install_one() {
  local name="$1"
  local label="io.local.mac-bootstrap.$name"
  local target="$TARGET_DIR/$label.plist"
  local temporary

  temporary="$(mktemp "$TARGET_DIR/.$label.XXXXXX")"
  trap 'rm -f "$temporary"' RETURN
  sed "s|{{BOOTSTRAP}}|$BOOTSTRAP|g" "$BOOTSTRAP/launchd/$label.plist" > "$temporary"
  if command -v plutil >/dev/null 2>&1; then
    plutil -lint "$temporary" >/dev/null
  fi
  chmod 644 "$temporary"

  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  mv "$temporary" "$target"
  trap - RETURN
  launchctl enable "$DOMAIN/$label"
  launchctl bootstrap "$DOMAIN" "$target"
  echo "Installed launch agent: $target"
}

mkdir -p "$TARGET_DIR"
for name in "${LABELS[@]}"; do
  label="io.local.mac-bootstrap.$name"
  if [[ "$ACTION" == install ]]; then
    install_one "$name"
  else
    launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
    echo "Unloaded launch agent: $label"
  fi
done
