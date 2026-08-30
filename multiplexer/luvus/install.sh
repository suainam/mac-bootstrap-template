#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Installing luvus (if missing) ==="
if ! command -v luvus &> /dev/null; then
    if command -v brew &> /dev/null; then
        brew tap rizriyz/luvus
        brew trust rizriyz/luvus 2>/dev/null || true
        brew install luvus
    else
        echo "Homebrew not found. Please install luvus manually: curl -fsSL https://luvus.dev/install.sh | sh"
    fi
else
    echo "  luvus is already installed ($(luvus --version))."
fi

echo "=== Linking config.json and manifests ==="
mkdir -p "$HOME/.luvus"
ln -sf "$DIR/config.json" "$HOME/.luvus/config.json"
echo "  ~/.luvus/config.json -> multiplexer/luvus/config.json"

if [ -d "$DIR/manifests" ]; then
    mkdir -p "$HOME/.luvus/manifests"
    for f in "$DIR/manifests"/*.toml; do
        [ -e "$f" ] || continue
        ln -sf "$f" "$HOME/.luvus/manifests/$(basename "$f")"
        echo "  ~/.luvus/manifests/$(basename "$f") -> multiplexer/luvus/manifests/$(basename "$f")"
    done
fi

echo "=== Linking local modules ==="
if [ -d "$DIR/modules/omp-monitor" ]; then
    luvus module link "$DIR/modules/omp-monitor" 2>/dev/null || true
    echo "  linked local.omp-monitor module"
fi

echo "Done. Luvus configuration is installed."
echo "You can start it by running 'luvus'."
