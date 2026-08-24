#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

cd "$REPO_ROOT"

log "validating Cloudflare Tunnel configuration; token output stays <redacted>"
./scripts/devspace-local.sh --dry-run tunnel-run >/dev/null

log "starting Cloudflare Tunnel with token <redacted>"
./scripts/devspace-local.sh tunnel-run &
CLOUDFLARED_PID=$!
trap 'kill "$CLOUDFLARED_PID" 2>/dev/null || true' TERM INT

# Watchdog: cloudflared can get stuck retrying a stale edge for hours while the
# network path is healthy again; a fresh process registers instantly. Probe the
# public endpoint and exit after repeated failures so launchd restarts us.
PUBLIC_MCP_URL="$(./scripts/devspace-local.sh public-url)"
CHECK_INTERVAL_SECONDS="${TUNNEL_CHECK_INTERVAL_SECONDS:-60}"
MAX_FAILURES="${TUNNEL_MAX_FAILURES:-5}"
failures=0
while kill -0 "$CLOUDFLARED_PID" 2>/dev/null; do
  sleep "$CHECK_INTERVAL_SECONDS"
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 --noproxy '*' "$PUBLIC_MCP_URL" 2>/dev/null || echo 000)"
  case "$code" in
    200|401|405)
      failures=0
      ;;
    *)
      failures=$((failures + 1))
      log "public /mcp unhealthy (HTTP $code); consecutive failures=$failures"
      if [ "$failures" -ge "$MAX_FAILURES" ]; then
        log "restarting cloudflared after $failures consecutive public probe failures"
        kill "$CLOUDFLARED_PID" 2>/dev/null || true
        wait "$CLOUDFLARED_PID" 2>/dev/null || true
        exit 1
      fi
      ;;
  esac
done
wait "$CLOUDFLARED_PID"
