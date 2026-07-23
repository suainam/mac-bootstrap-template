#!/usr/bin/env bash

# Enable Gemini in Chrome by patching Local State
# This script applies the patch silently. It can be bound to upgrade hooks or run manually.

set -euo pipefail

CHROME_STATE="$HOME/Library/Application Support/Google/Chrome/Local State"

echo "🚀 Patching Google Chrome to enable Gemini features..."

if [ ! -f "$CHROME_STATE" ]; then
    echo "⚠️ Chrome config not found: $CHROME_STATE. Skipping patch."
    exit 0
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

if pgrep -x "Google Chrome" > /dev/null; then
    echo "⚠️  WARNING: Chrome is currently running."
    echo "   The patch will be applied, but Chrome might overwrite it when you quit."
    echo "   If Gemini disappears later, close Chrome and run: make patch-chrome-gemini"
fi

# Apply the patch using sed directly on the file
sed -i '' -e 's/"is_glic_eligible":[[:space:]]*false/"is_glic_eligible":true/g' \
          -e 's/"variations_country":"[^"]*"/"variations_country":"us"/g' \
          -e 's/\("variations_permanent_consistency_country":\[[^]]*\)"[^"]*"\]/\1"us"]/g' \
          "$CHROME_STATE"

echo "✅ Chrome Gemini patch applied successfully."
