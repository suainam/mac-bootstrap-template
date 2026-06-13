#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Linking tmux.conf ==="
ln -sf "$DIR/tmux.conf" ~/.tmux.conf
echo "  ~/.tmux.conf -> tmux/tmux.conf"

echo "=== Linking default theme (catppuccin-mocha) ==="
mkdir -p ~/.tmux
ln -sf "$DIR/themes/catppuccin-mocha.conf" ~/.tmux/theme.conf
echo "  ~/.tmux/theme.conf -> tmux/themes/catppuccin-mocha.conf"

echo "=== Install tmux plugin manager (tpm) ==="
TPM_DIR="$HOME/.tmux/plugins/tpm"
if [ ! -d "$TPM_DIR" ]; then
  git clone https://github.com/tmux-plugins/tpm "$TPM_DIR"
fi

echo "Done. Enter tmux and press prefix+I to install plugins."
echo "To switch themes: tmux/switch-theme.sh <catppuccin-mocha|gruvbox-dark>"
