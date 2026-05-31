#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Linking vimrc ==="
ln -sf "$DIR/vimrc" ~/.vimrc

echo "=== Installing vim-plug ==="
curl -fLo ~/.vim/autoload/plug.vim --create-dirs \
  https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim

echo "=== Installing plugins ==="
vim +PlugInstall +qall

echo "Vim setup done."
