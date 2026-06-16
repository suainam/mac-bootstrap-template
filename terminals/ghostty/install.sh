#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HOME/.config/ghostty"

echo "=== Install Ghostty config ==="
mkdir -p "$TARGET"
ln -sf "$DIR/config" "$TARGET/config"
echo "  $TARGET/config -> terminals/ghostty/config"

if [ ! -f "$TARGET/theme.local" ]; then
  cat >"$TARGET/theme.local" <<'EOF'
# Managed by switch-terminal-theme.sh
theme = "Catppuccin Mocha"
EOF
  echo "  Created $TARGET/theme.local"
fi

echo "=== Sync Ghostty terminfo to ~/.terminfo for compatibility ==="
GHOSTTY_TERMINFO="/Applications/Ghostty.app/Contents/Resources/terminfo"
if [ -d "$GHOSTTY_TERMINFO" ]; then
  mkdir -p "$HOME/.terminfo/78" "$HOME/.terminfo/67"
  cp "$GHOSTTY_TERMINFO/78/xterm-ghostty" "$HOME/.terminfo/78/xterm-ghostty"
  cp "$GHOSTTY_TERMINFO/67/ghostty" "$HOME/.terminfo/67/ghostty"
  echo "  Copied ghostty terminfo files to ~/.terminfo"
else
  echo "  Ghostty.app not found in /Applications, skipping terminfo sync"
fi

echo "Done. Restart Ghostty to apply."
