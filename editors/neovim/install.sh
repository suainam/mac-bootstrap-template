#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_SRC="$DIR/config"
CONFIG_DST="$HOME/.config/nvim"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
PY_HOST_DIR="$HOME/.local/share/neovim-python"
PY_HOST_PYTHON="$PY_HOST_DIR/bin/python"

backup_if_needed() {
  local path="$1"
  if [ -L "$path" ]; then
    local target
    target="$(readlink "$path")"
    if [ "$target" = "$CONFIG_SRC" ]; then
      return 0
    fi
    rm -f "$path"
    return 0
  fi

  if [ -e "$path" ]; then
    mv "$path" "${path}.bak.${TIMESTAMP}"
    echo "  Backed up $path -> ${path}.bak.${TIMESTAMP}"
  fi
}

echo "=== Install Neovim + LazyVim config ==="
if ! command -v nvim >/dev/null 2>&1; then
  echo "nvim not found in PATH. Install Brewfile dependencies first." >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found in PATH. Install Brewfile dependencies first." >&2
  exit 1
fi

mkdir -p "$HOME/.config"
backup_if_needed "$CONFIG_DST"
ln -sfn "$CONFIG_SRC" "$CONFIG_DST"
echo "  ~/.config/nvim -> editors/neovim/config"

echo "=== Provision dedicated Neovim Python host (uv-managed) ==="
mkdir -p "$(dirname "$PY_HOST_DIR")"
uv venv "$PY_HOST_DIR"
uv pip install --python "$PY_HOST_PYTHON" pynvim
echo "  Python host -> $PY_HOST_PYTHON"

git config --global core.editor "nvim"
git config --global sequence.editor "nvim"

echo "=== Sync LazyVim plugins ==="
nvim --headless "+Lazy! sync" +qa || true

echo "=== Warm up parsers/providers ==="
nvim --headless "+checkhealth" +qa || true

echo "Done. Launch with: nvim"
