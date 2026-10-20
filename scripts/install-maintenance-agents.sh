#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
ACTION="${1:-install}"
SELECTION="${2:-all}"

TEMPORARY=""
BACKUP=""

cleanup_temporary_files() {
  [[ -z "$TEMPORARY" ]] || rm -f "$TEMPORARY" || true
  [[ -z "$BACKUP" ]] || rm -f "$BACKUP" || true
}
trap cleanup_temporary_files EXIT


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
restore_previous() {
  local target="$1"
  local label="$2"
  local revert_enabled="$3"

  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  if [[ -z "$BACKUP" ]]; then
    if ! rm -f "$target"; then
      echo "Could not remove failed LaunchAgent: $target" >&2
    fi
    if [[ "$revert_enabled" == true ]] && ! launchctl disable "$DOMAIN/$label"; then
      echo "Could not disable failed LaunchAgent: $label" >&2
    fi
    return 0
  fi
  if ! mv "$BACKUP" "$target"; then
    echo "Could not restore previous LaunchAgent; backup remains at $BACKUP" >&2
    BACKUP=""
    return 1
  fi
  BACKUP=""
  if ! launchctl bootstrap "$DOMAIN" "$target" >/dev/null 2>&1; then
    echo "Restored previous plist but could not bootstrap LaunchAgent: $label" >&2
    return 1
  fi
}

install_one() {
  local name="$1"
  local label="io.local.mac-bootstrap.$name"
  local script
  local target="$TARGET_DIR/$label.plist"
  local plist_script
  local escaped_path
  local status

  case "$name" in
    claude-daemon) script=claude-daemon.sh ;;
    cache-cleanup) script=clean-cache.sh ;;
    downloads-organizer) script=organize-downloads.sh ;;
    system-patrol) script=system-patrol.sh ;;
  esac
  plist_script="$BOOTSTRAP/scripts/$script"

  TEMPORARY="$(mktemp "$TARGET_DIR/.$label.XXXXXX")"
  escaped_path=${plist_script//\\/\\\\}
  escaped_path=${escaped_path//\'/\\\'}
  cp "$BOOTSTRAP/launchd/$label.plist" "$TEMPORARY"
  /usr/libexec/PlistBuddy -c "Set :ProgramArguments:1 '$escaped_path'" "$TEMPORARY"
  plutil -lint "$TEMPORARY" >/dev/null
  chmod 644 "$TEMPORARY"

  if [[ -e "$target" ]]; then
    BACKUP="$(mktemp "$TARGET_DIR/.$label.backup.XXXXXX")"
    cp -p "$target" "$BACKUP"
  fi

  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  if mv "$TEMPORARY" "$target"; then
    TEMPORARY=""
  else
    status=$?
    restore_previous "$target" "$label" false || true
    return "$status"
  fi

  if launchctl enable "$DOMAIN/$label"; then
    :
  else
    status=$?
    restore_previous "$target" "$label" true || true
    return "$status"
  fi
  if launchctl bootstrap "$DOMAIN" "$target"; then
    :
  else
    status=$?
    restore_previous "$target" "$label" true || true
    return "$status"
  fi

  if [[ -n "$BACKUP" ]]; then
    rm -f "$BACKUP" || true
    BACKUP=""
  fi
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
