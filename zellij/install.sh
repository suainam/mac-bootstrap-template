#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$HOME/.config/zellij"
LAYOUT_DIR="$CONFIG_DIR/layouts"
CONFIG_FILE="$CONFIG_DIR/config.kdl"

echo "=== Linking Zellij layouts ==="
mkdir -p "$LAYOUT_DIR"

for layout in "$DIR"/layouts/*.kdl; do
  [ -f "$layout" ] || continue
  name="$(basename "$layout")"
  ln -sf "$layout" "$LAYOUT_DIR/$name"
  echo "  $LAYOUT_DIR/$name -> zellij/layouts/$name"
done

echo "=== Linking Zellij config ==="
if [ -f "$DIR/config.kdl" ]; then
  ln -sf "$DIR/config.kdl" "$CONFIG_FILE"
  echo "  $CONFIG_FILE -> zellij/config.kdl"
fi

echo 'Done. Use `zellij` for the default workspace or `zellij --layout ai-work` for the starter layout.'
