#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
BOOTSTRAP="$(cd "$DIR/.." && pwd)"

. "$BOOTSTRAP/scripts/lib/agent-shared.sh"

load_x_mcp_private_env

if [ "${X_MCP_ENABLE:-0}" != "1" ]; then
  echo "xapi MCP disabled: set enabled=true in private/agent/x-mcp.jsonc" >&2
  exit 1
fi

if [ -z "${X_MCP_CLIENT_ID:-}" ] || [ -z "${X_MCP_CLIENT_SECRET:-}" ]; then
  echo "xapi MCP missing credentials in private/agent/x-mcp.jsonc" >&2
  exit 1
fi

export CLIENT_ID="$X_MCP_CLIENT_ID"
export CLIENT_SECRET="$X_MCP_CLIENT_SECRET"
if [ -n "${X_MCP_CALLBACK_URL:-}" ]; then
  export REDIRECT_URI="$X_MCP_CALLBACK_URL"
fi

exec npx -y @xdevplatform/xurl mcp https://api.x.com/mcp
