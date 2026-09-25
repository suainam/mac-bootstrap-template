#!/usr/bin/env bash

# Enable Gemini in Chrome by patching Local State
# This script applies the patch silently. It can be bound to upgrade hooks or run manually.

set -euo pipefail

TARGET_USER="${1:-$USER}"
TARGET_HOME="$(eval echo "~$TARGET_USER")"
CHROME_STATE="$TARGET_HOME/Library/Application Support/Google/Chrome/Local State"

echo "🚀 Patching Google Chrome for user '$TARGET_USER' to enable Gemini features..."

if [ ! -f "$CHROME_STATE" ]; then
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
if grep -q '"variations_country":"[^"]*"' "$CHROME_STATE" && ! grep -q '"variations_country":"us"' "$CHROME_STATE"; then
    NEEDS_PATCH=1
fi
if grep -q '"variations_permanent_consistency_country":\[[^]]*\]' "$CHROME_STATE" && ! grep -q '"variations_permanent_consistency_country":\[[^]]*"us"\]' "$CHROME_STATE"; then
    NEEDS_PATCH=1
fi

if [ $NEEDS_PATCH -eq 0 ]; then
    echo "✨ Gemini patch is already active. No changes needed."
    exit 0
fi

if pgrep -u "$TARGET_USER" -x "Google Chrome" > /dev/null 2>&1; then
    echo "⚠️  WARNING: Chrome is currently running for user '$TARGET_USER'."
    echo "   The patch will be applied, but Chrome might overwrite it when quit."
    echo "   If Gemini disappears, close Chrome and rerun: make patch-chrome-gemini USER=$TARGET_USER"
fi

# Apply the patch using sed directly on the file
sed -i '' -e 's/"is_glic_eligible":[[:space:]]*false/"is_glic_eligible":true/g' \
          -e 's/"variations_country":"[^"]*"/"variations_country":"us"/g' \
          -e 's/\("variations_permanent_consistency_country":\[[^]]*\)"[^"]*"\]/\1"us"]/g' \
          "$CHROME_STATE"

echo "✅ Chrome Gemini patch applied successfully."
