#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
LIB="$DIR/scripts/lib/proxy-common.sh"
GIT_PROXY_TARGET="$HOME/.gitconfig.proxy"

. "$LIB"

echo "=== npm proxy ==="
npm config delete proxy >/dev/null 2>&1 || true
npm config delete https-proxy >/dev/null 2>&1 || true
echo "  npm proxy cleared"

echo "=== git proxy ==="
clear_git_proxy_include "$GIT_PROXY_TARGET"
echo "  git proxy include cleared"

echo ""
echo "Shell env remains the source of truth. Open a new shell or run unsetproxy if needed."
