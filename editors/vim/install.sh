#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Linking vimrc ==="
ln -sf "$DIR/vimrc" ~/.vimrc
echo "  ~/.vimrc -> vim/vimrc"

echo "=== Linking default theme (catppuccin-mocha) ==="
mkdir -p ~/.vim
ln -sf "$DIR/themes/catppuccin-mocha.vim" ~/.vim/theme.vim
echo "  ~/.vim/theme.vim -> vim/themes/catppuccin-mocha.vim"

echo "=== Installing vim-plug ==="
if [ ! -f ~/.vim/autoload/plug.vim ]; then
  curl -fLo ~/.vim/autoload/plug.vim --create-dirs \
    https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim
else
  echo "  vim-plug already installed"
fi

echo "=== Installing plugins ==="
vim +PlugUpdate +qall 2>/dev/null || vim +PlugInstall +qall 2>/dev/null || true

echo "Done. To switch themes: vim/switch-theme.sh <catppuccin-mocha|gruvbox-dark>"
