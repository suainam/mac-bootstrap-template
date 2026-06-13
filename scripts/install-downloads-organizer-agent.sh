#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/io.local.mac-bootstrap.downloads-organizer.plist"

mkdir -p "$TARGET_DIR"
if [ -f "$TARGET_PLIST" ] && cmp -s "$DIR/launchd/io.local.mac-bootstrap.downloads-organizer.plist" "$TARGET_PLIST"; then
  echo "Plist unchanged, skipping copy"
else
  cp "$DIR/launchd/io.local.mac-bootstrap.downloads-organizer.plist" "$TARGET_PLIST"
fi
launchctl unload "$TARGET_PLIST" >/dev/null 2>&1 || true
launchctl load "$TARGET_PLIST"

echo "Installed launch agent: $TARGET_PLIST"
echo "Schedule: every 30 minutes"
