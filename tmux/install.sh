#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Linking tmux.conf ==="
ln -sf "$DIR/tmux.conf" ~/.tmux.conf
echo "  ~/.tmux.conf -> tmux/tmux.conf"

echo "=== Install tmux plugin manager (tpm) ==="
TPM_DIR="$HOME/.tmux/plugins/tpm"
if [ ! -d "$TPM_DIR" ]; then
  git clone https://github.com/tmux-plugins/tpm "$TPM_DIR"
fi

echo "Done. Enter tmux and press prefix+I to install plugins."
