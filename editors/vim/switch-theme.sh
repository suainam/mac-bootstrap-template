#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
THEMES_DIR="$DIR/themes"
LINK="$HOME/.vim/theme.vim"

usage() {
  echo "Usage: $(basename "$0") <theme-name>"
  echo ""
  echo "Available themes:"
  for f in "$THEMES_DIR"/*.vim; do
    [ -f "$f" ] || continue
    local name
    name="$(basename "$f" .vim)"
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
THEME_FILE="$THEMES_DIR/$THEME.vim"

[[ ! -f "$THEME_FILE" ]] && {
  echo "Error: theme '$THEME' not found in $THEMES_DIR"
  echo ""
  usage
}

mkdir -p ~/.vim
ln -sf "$THEME_FILE" "$LINK"
echo "Switched to: $THEME"
echo "Restart vim or run :source ~/.vim/theme.vim to apply."
