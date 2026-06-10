#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HOME/.hammerspoon"
SPOONS="$TARGET/Spoons"

install_spoon() {
  local name="$1"
  local url="https://github.com/Hammerspoon/Spoons/raw/master/Spoons/${name}.spoon.zip"
  local dest="$SPOONS/${name}.spoon"
  local tmpdir
  tmpdir="$(mktemp -d)"

  if [[ -d "$dest" ]]; then
    echo "  $name already installed"
    rm -rf "$tmpdir"
    return
  fi

  echo "  downloading $name from official Spoons repo"
  curl -fsSL "$url" -o "$tmpdir/${name}.zip"
  unzip -q "$tmpdir/${name}.zip" -d "$tmpdir"
  mkdir -p "$SPOONS"
  rm -rf "$dest"
  mv "$tmpdir/${name}.spoon" "$SPOONS/"
  rm -rf "$tmpdir"
}

echo "=== Linking Hammerspoon config ==="
mkdir -p "$TARGET"
ln -sf "$DIR/init.lua" "$TARGET/init.lua"
echo "  $TARGET/init.lua -> hammerspoon/init.lua"

echo "=== Installing official Spoons ==="
install_spoon "ClipboardTool"
install_spoon "HSKeybindings"



echo "Done. Reload Hammerspoon after opening the app once."
