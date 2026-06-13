#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PRESETS_DIR="$HOME/Library/Application Support/iTerm2/ColorPresets"
PLIST_PATH="$HOME/Library/Preferences/com.googlecode.iterm2.plist"

echo "=== Install iTerm2 color presets ==="
mkdir -p "$PRESETS_DIR"

# install all .itermcolors from themes/
for scheme_file in "$DIR/themes/"*.itermcolors; do
  [ -f "$scheme_file" ] || continue
  name="$(basename "$scheme_file" .itermcolors)"
  cp "$scheme_file" "$PRESETS_DIR/$name.itermcolors"
  echo "  $name -> $PRESETS_DIR/"

  python3 - "$PRESETS_DIR/$name.itermcolors" "$name" <<'PYEOF'
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
done

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
    handlers[:] = [h for h in handlers if h.get('LSHandlerURLScheme') != 'terminal']
    handlers.append(entry)
    with open(plist_path, 'wb') as f:
        plistlib.dump(config, f)
    print('  iTerm2 registered as default terminal')
else:
    print('  iTerm2 already default terminal')
"

echo ""
echo "Installed themes:"
ls -1 "$PRESETS_DIR/"*.itermcolors 2>/dev/null | xargs -I{} basename {} .itermcolors | sed 's/^/  /'
echo ""
echo "Restart iTerm2, then: Profiles -> Colors -> Color Presets -> select theme."
