#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
SHELL_ENV="$DIR/shell/shell_env"

if [ ! -f "$SHELL_ENV" ]; then
  echo "Error: $SHELL_ENV not found" >&2
  exit 1
fi

HTTP_PROXY_VAL=$(grep '^export http_proxy=' "$SHELL_ENV" | sed 's/.*=//' | tr -d '"')
HTTPS_PROXY_VAL=$(grep '^export https_proxy=' "$SHELL_ENV" | sed 's/.*=//' | tr -d '"')

if [ -z "$HTTP_PROXY_VAL" ] || [ -z "$HTTPS_PROXY_VAL" ]; then
  echo "Error: proxy values not found in $SHELL_ENV" >&2
  exit 1
fi

echo "=== npm proxy ==="
npm config set proxy "$HTTP_PROXY_VAL"
npm config set https-proxy "$HTTPS_PROXY_VAL"
echo "  npm proxy configured"

echo ""
echo "Source: shell/shell_env  |  Docker/Colima reads env vars automatically"
