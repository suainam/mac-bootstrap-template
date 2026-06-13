#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
THEMES_DIR="$DIR/themes"
LINK="$HOME/.tmux/theme.conf"

usage() {
  echo "Usage: $(basename "$0") <theme-name>"
  echo ""
  echo "Available themes:"
  for f in "$THEMES_DIR"/*.conf; do
    local name
    name="$(basename "$f" .conf)"
    if [ -L "$LINK" ] && [ "$(readlink "$LINK")" = "$f" ]; then
      echo "  $name  (active)"
    else
      echo "  $name"
    fi
  done
  exit 1
}

[[ $# -lt 1 ]] && usage

THEME="$1"
THEME_FILE="$THEMES_DIR/$THEME.conf"

[[ ! -f "$THEME_FILE" ]] && {
  echo "Error: theme '$THEME' not found in $THEMES_DIR"
  echo ""
  usage
}

ln -sf "$THEME_FILE" "$LINK"
echo "Switched to: $THEME"

# reload tmux if running
if command -v tmux &>/dev/null && tmux list-sessions &>/dev/null 2>&1; then
  tmux source-file ~/.tmux.conf 2>/dev/null && echo "tmux reloaded." || echo "Run 'tmux source ~/.tmux.conf' to apply."
fi
