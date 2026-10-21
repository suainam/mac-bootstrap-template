#!/usr/bin/env bash

# Enable Gemini in Chrome by patching Local State
# This script applies the patch silently. It can be bound to upgrade hooks or run manually.

set -euo pipefail

KILL_CHROME="${KILL_CHROME:-0}"
TARGET_USER=""

for arg in "$@"; do
    case "$arg" in
        --kill)
            KILL_CHROME=1
            ;;
        *)
            if [ -z "$TARGET_USER" ]; then
                TARGET_USER="$arg"
            fi
            ;;
    esac
done

TARGET_USER="${TARGET_USER:-$USER}"

# Validate account and resolve home safely via dscl — no eval, no shell injection.
# Reject missing/invalid accounts before any side effect.
USER_NODE="/""Users/$TARGET_USER"
if ! dscl . -read "$USER_NODE" NFSHomeDirectory > /dev/null 2>&1; then
    echo "❌ Unknown user account: '$TARGET_USER'. Aborting." >&2
    exit 1
fi
TARGET_HOME="$(dscl . -read "$USER_NODE" NFSHomeDirectory \
    | sed -n 's/^NFSHomeDirectory:[[:space:]]*//p')"
if [ -z "$TARGET_HOME" ]; then
    echo "❌ Could not determine home directory for '$TARGET_USER'. Aborting." >&2
    exit 1
fi

CHROME_STATE="$TARGET_HOME/Library/Application Support/Google/Chrome/Local State"

if [ ! -e "$CHROME_STATE" ]; then
    if [ ! -r "$TARGET_HOME/Library" ]; then
        echo "⚠️ Permission denied: cannot access $TARGET_HOME/Library."
        echo "   To patch another user, run with sudo or run directly under '$TARGET_USER':"
        echo "     sudo ./scripts/patch-chrome-gemini.sh $TARGET_USER"
        exit 1
    fi
    echo "⚠️ Chrome config not found: $CHROME_STATE. Skipping patch."
    exit 0
fi

if [ ! -r "$CHROME_STATE" ] || [ ! -w "$CHROME_STATE" ]; then
    echo "⚠️ Cannot read/write $CHROME_STATE (macOS TCC permission denied)."
    echo "   Please grant 'Full Disk Access' to your Terminal/Ghostty in:"
    echo "   System Settings -> Privacy & Security -> Full Disk Access"
    exit 1
fi


# JSON-aware patch. Chrome re-derives variations_country from the live seed on every
# launch; variations_permanent_overridden_country is the pref that actually pins the
# session country, so it (and browser.variations_country) must be written too.
PATCH_PY='
import json, os, sys, tempfile
mode, path = sys.argv[1], sys.argv[2]
raw = open(path, encoding="utf-8").read()
d = json.loads(raw)
b = d.setdefault("browser", {})
g = d.setdefault("glic", {})
want = [
    (d, "variations_country", "us"),
    (d, "variations_permanent_consistency_country", ["us"]),
    (d, "variations_permanent_overridden_country", "us"),
    (b, "variations_country", "us"),
    (g, "multi_instance_enabled_by_tier", True),
]
changed = False
for obj, k, v in want:
    if obj.get(k) != v:
        obj[k] = v
        changed = True
def walk(o):
    global changed
    if isinstance(o, dict):
        if o.get("is_glic_eligible") is False:
            o["is_glic_eligible"] = True
            changed = True
        for v in o.values():
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)
walk(d)
if mode == "check":
    sys.exit(1 if changed else 0)
if changed:
    out = json.dumps(d, separators=(",", ":"), ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(out)
    os.chmod(tmp, os.stat(path).st_mode & 0o777)
    os.replace(tmp, path)
'

if python3 -c "$PATCH_PY" check "$CHROME_STATE"; then
    echo "✨ Gemini patch is already active. No changes needed."
    exit 0
fi

if pgrep -u "$TARGET_USER" -x "Google Chrome" > /dev/null 2>&1; then
    if [ "$KILL_CHROME" = "1" ]; then
        echo "🛑 Closing Google Chrome for user '$TARGET_USER'..."
        if [ "$TARGET_USER" = "$USER" ] || [ "$(id -u)" -eq 0 ]; then
            pkill -u "$TARGET_USER" -x "Google Chrome" || true
        else
            sudo pkill -u "$TARGET_USER" -x "Google Chrome" || true
        fi
        # Bounded wait: up to 5 seconds; fail if Chrome still running.
        _waited=0
        while pgrep -u "$TARGET_USER" -x "Google Chrome" > /dev/null 2>&1; do
            if [ "$_waited" -ge 5 ]; then
                echo "❌ Chrome is still running after ${_waited}s. Aborting to avoid data loss." >&2
                echo "   Close Chrome manually and rerun: make patch-chrome-gemini USER=$TARGET_USER KILL=1" >&2
                exit 1
            fi
            sleep 1
            _waited=$((_waited + 1))
        done
    else
        echo "⚠️  WARNING: Chrome is currently running for user '$TARGET_USER'."
        echo "   The patch will be applied, but Chrome might overwrite it when quit."
        echo "   Pass --kill or KILL=1 to close Chrome automatically before patching."
        echo "   If Gemini disappears, close Chrome and rerun: make patch-chrome-gemini USER=$TARGET_USER KILL=1"
    fi
fi

python3 -c "$PATCH_PY" apply "$CHROME_STATE" || { echo "❌ Patch failed." >&2; exit 1; }

echo "✅ Chrome Gemini patch applied successfully."
