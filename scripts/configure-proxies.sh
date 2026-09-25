#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
SHELL_ENV="$DIR/shell/shell_env"
GIT_PROXY_TEMPLATE="$DIR/shell/gitconfig.proxy.template"
GIT_PROXY_TARGET="$HOME/.gitconfig.proxy"
LIB="$DIR/scripts/lib/proxy-common.sh"

. "$LIB"
load_proxy_env_from_shell_env "$SHELL_ENV"
require_proxy_values

echo "=== npm proxy ==="
npm config set proxy "$HTTP_PROXY_VAL"
npm config set https-proxy "$HTTPS_PROXY_VAL"
echo "  npm proxy configured"

echo "=== git proxy ==="
write_git_proxy_include "$GIT_PROXY_TEMPLATE" "$GIT_PROXY_TARGET"
echo "  git proxy include configured at $GIT_PROXY_TARGET ($HTTP_PROXY_VAL)"

echo ""
echo "Source: shell/shell_env  |  Docker/Colima reads env vars automatically"
echo ""
echo "Notice: Active shell sessions and background agents (Herdr panes / tmux) retain existing environment."
echo "  Run: source ~/.zshrc (or restart agent session) to pick up the updated proxy variables."
