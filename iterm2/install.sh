#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PRESETS_DIR="$HOME/Library/Application Support/iTerm2/ColorPresets"
PRESET_NAME="GruvboxDark"

echo "=== Install iTerm2 color preset: $PRESET_NAME ==="
mkdir -p "$PRESETS_DIR"
cp "$DIR/$PRESET_NAME.itermcolors" "$PRESETS_DIR/$PRESET_NAME.itermcolors"

# Inject into iTerm2's user defaults (idempotent — replaces if exists)
python3 -c "
import plistlib
from pathlib import Path

plist_path = Path.home() / 'Library/Preferences/com.googlecode.iterm2.plist'
preset_path = Path.home() / 'Library/Application Support/iTerm2/ColorPresets/$PRESET_NAME.itermcolors'

with open(preset_path, 'rb') as f:
    preset = plistlib.load(f)

try:
    with open(plist_path, 'rb') as f:
        config = plistlib.load(f)
except Exception:
    config = {}

config.setdefault('Custom Color Presets', {})['$PRESET_NAME'] = preset

with open(plist_path, 'wb') as f:
    plistlib.dump(config, f)

print('  Color preset registered in iTerm2 plist')
"
echo "  $PRESETS_DIR/$PRESET_NAME.itermcolors"

echo "=== Set iTerm2 as default terminal ==="
python3 -c "
import plistlib
from pathlib import Path

plist_path = Path.home() / 'Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist'
entry = {
    'LSHandlerURLScheme': 'terminal',
    'LSHandlerRoleAll': 'com.googlecode.iterm2',
}

try:
    with open(plist_path, 'rb') as f:
        config = plistlib.load(f)
except Exception:
    config = {'LSHandlers': []}

handlers = config.setdefault('LSHandlers', [])
exists = any(
    h.get('LSHandlerURLScheme') == 'terminal' and h.get('LSHandlerRoleAll') == 'com.googlecode.iterm2'
    for h in handlers
)

if not exists:
    # Remove any other terminal handler first
    handlers[:] = [h for h in handlers if h.get('LSHandlerURLScheme') != 'terminal']
    handlers.append(entry)
    with open(plist_path, 'wb') as f:
        plistlib.dump(config, f)
    print('  iTerm2 registered as default terminal')
else:
    print('  iTerm2 already default terminal')
"

echo "Done. Restart iTerm2 and select $PRESET_NAME in Profiles → Colors → Color Presets."
