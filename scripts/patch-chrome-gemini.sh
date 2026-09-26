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
# Disable IPv6 on Wi-Fi/Ethernet if enabled, preventing domestic ISP IPv6 from leaking to Google
if command -v networksetup &>/dev/null; then
    for svc in "Wi-Fi" "Ethernet"; do
        if networksetup -listallnetworkservices 2>/dev/null | grep -qx "$svc"; then
            v6_info="$(networksetup -getinfo "$svc" 2>/dev/null | grep -E '^IPv6:' || true)"
            if [ -n "$v6_info" ] && [[ "$v6_info" != *"Off"* ]]; then
                echo "⚠️ IPv6 is active on $svc ($v6_info), which leaks domestic ISP IP to Google."
                echo "   Disabling IPv6 on $svc to prevent Happy Eyeballs region lock..."
                networksetup -setv6off "$svc" 2>/dev/null || true
            fi
        fi
    done
fi


# Check if patching is even needed
NEEDS_PATCH=0
if grep -q '"is_glic_eligible":[[:space:]]*false' "$CHROME_STATE"; then
    NEEDS_PATCH=1
fi
if grep -q '"variations_country":[[:space:]]*"[^"]*"' "$CHROME_STATE" && ! grep -q '"variations_country":[[:space:]]*"us"' "$CHROME_STATE"; then
    NEEDS_PATCH=1
fi
if grep -q '"variations_permanent_consistency_country":[[:space:]]*\[[^]]*\]' "$CHROME_STATE" && ! grep -q '"variations_permanent_consistency_country":[[:space:]]*\[[[:space:]]*"us"[[:space:]]*\]' "$CHROME_STATE"; then
    NEEDS_PATCH=1
fi

if [ $NEEDS_PATCH -eq 0 ]; then
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

# Apply the patch using sed directly on the file
sed -i '' -e 's/"is_glic_eligible":[[:space:]]*false/"is_glic_eligible":true/g' \
          -e 's/"variations_country":[[:space:]]*"[^"]*"/"variations_country":"us"/g' \
          -e 's/\("variations_permanent_consistency_country":[[:space:]]*\[\)[^]]*\]/\1"us"]/g' \
          "$CHROME_STATE"

echo "✅ Chrome Gemini patch applied successfully."
