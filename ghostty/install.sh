#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="/Applications/Ghostty.app"
PLIST_PATH="$APP_PATH/Contents/Info.plist"
LAUNCHSERVICES_PLIST="$HOME/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"
CONFIG_DIR="$HOME/.config/ghostty"
CONFIG_FILE="$CONFIG_DIR/config"

echo "=== Linking Ghostty config ==="
mkdir -p "$CONFIG_DIR"
ln -sf "$DIR/config" "$CONFIG_FILE"
echo "  $CONFIG_FILE -> ghostty/config"

echo "=== Configure Ghostty as default terminal ==="

if [ ! -f "$PLIST_PATH" ]; then
  echo "  Ghostty app not found at $APP_PATH; skip default-terminal registration."
  exit 0
fi

BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$PLIST_PATH" 2>/dev/null || true)"
if [ -z "$BUNDLE_ID" ]; then
  BUNDLE_ID="$(plutil -extract CFBundleIdentifier raw -o - "$PLIST_PATH" 2>/dev/null || true)"
fi

if [ -z "$BUNDLE_ID" ]; then
  echo "  Could not read Ghostty bundle identifier; skip default-terminal registration."
  exit 0
fi

BUNDLE_ID="$BUNDLE_ID" LAUNCHSERVICES_PLIST="$LAUNCHSERVICES_PLIST" python3 - <<'PY'
import os
import plistlib
from pathlib import Path

plist_path = Path(os.environ["LAUNCHSERVICES_PLIST"])
bundle_id = os.environ["BUNDLE_ID"]
entry = {
    "LSHandlerURLScheme": "terminal",
    "LSHandlerRoleAll": bundle_id,
}

try:
    with open(plist_path, "rb") as f:
        config = plistlib.load(f)
except Exception:
    config = {"LSHandlers": []}

handlers = config.setdefault("LSHandlers", [])
exists = any(
    h.get("LSHandlerURLScheme") == "terminal" and h.get("LSHandlerRoleAll") == bundle_id
    for h in handlers
)

if not exists:
    handlers[:] = [h for h in handlers if h.get("LSHandlerURLScheme") != "terminal"]
    handlers.append(entry)
    with open(plist_path, "wb") as f:
        plistlib.dump(config, f)
    print(f"  Ghostty registered as default terminal ({bundle_id})")
else:
    print(f"  Ghostty already default terminal ({bundle_id})")
PY

echo "Done. Relaunch Ghostty if macOS does not pick up the terminal-handler change immediately."
