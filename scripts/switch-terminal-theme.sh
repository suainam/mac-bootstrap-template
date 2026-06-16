#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
GHOSTTY_THEME_FILE="$HOME/.config/ghostty/theme.local"
TMUX_SWITCH_SCRIPT="$ROOT/multiplexer/tmux/switch-theme.sh"

usage() {
  cat <<'EOF'
Usage: switch-terminal-theme.sh <theme-name>

Available themes:
  catppuccin-mocha
  gruvbox-dark
EOF
  exit 1
}

[[ $# -lt 1 ]] && usage

THEME="$1"

case "$THEME" in
  catppuccin-mocha)
    GHOSTTY_THEME_NAME="Catppuccin Mocha"
    ;;
  gruvbox-dark)
    GHOSTTY_THEME_NAME="Gruvbox Dark"
    ;;
  *)
    echo "Error: unsupported theme '$THEME'" >&2
    echo "" >&2
    usage
    ;;
esac

mkdir -p "$(dirname "$GHOSTTY_THEME_FILE")"
cat >"$GHOSTTY_THEME_FILE" <<EOF
# Managed by switch-terminal-theme.sh
theme = "$GHOSTTY_THEME_NAME"
EOF

"$TMUX_SWITCH_SCRIPT" "$THEME"

echo "Ghostty theme override -> $GHOSTTY_THEME_FILE ($GHOSTTY_THEME_NAME)"
echo "Restart Ghostty windows to apply terminal chrome/palette changes."
