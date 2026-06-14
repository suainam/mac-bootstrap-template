#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HOME/.config/ghostty"

echo "=== Install Ghostty config ==="
mkdir -p "$TARGET"
ln -sf "$DIR/config" "$TARGET/config"
echo "  $TARGET/config -> terminals/ghostty/config"

echo "Done. Restart Ghostty to apply."
