#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
THEMES_DIR="$DIR/themes"

usage() {
  echo "Usage: $(basename "$0") <theme-name>"
  echo ""
  echo "Available themes:"
  for f in "$THEMES_DIR"/*.itermcolors; do
    [ -f "$f" ] && echo "  $(basename "$f" .itermcolors)"
  done
  exit 1
}

[[ $# -lt 1 ]] && usage

THEME="$1"
THEME_FILE="$THEMES_DIR/$THEME.itermcolors"

[[ ! -f "$THEME_FILE" ]] && {
  echo "Error: theme '$THEME' not found in $THEMES_DIR"
  echo ""
  usage
}

# Copy to iTerm2 ColorPresets
PRESETS_DIR="$HOME/Library/Application Support/iTerm2/ColorPresets"
mkdir -p "$PRESETS_DIR"
cp "$THEME_FILE" "$PRESETS_DIR/$THEME.itermcolors"

# Register in iTerm2 plist
python3 - "$PRESETS_DIR/$THEME.itermcolors" "$THEME" <<'PYEOF'
import plistlib, sys
from pathlib import Path

preset_path = Path(sys.argv[1])
theme_name  = sys.argv[2]
plist_path  = Path.home() / 'Library/Preferences/com.googlecode.iterm2.plist'

with open(preset_path, 'rb') as f:
    preset = plistlib.load(f)

try:
    with open(plist_path, 'rb') as f:
        config = plistlib.load(f)
except Exception:
    config = {}

config.setdefault('Custom Color Presets', {})[theme_name] = preset

with open(plist_path, 'wb') as f:
    plistlib.dump(config, f)
PYEOF

echo "Installed '$THEME' into iTerm2."
echo "Open iTerm2 -> Profiles -> Colors -> Color Presets -> $THEME"
