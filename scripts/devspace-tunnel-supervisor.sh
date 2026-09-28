#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export TUNNEL_METRICS="${TUNNEL_METRICS:-localhost:0}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

cd "$REPO_ROOT"
PROFILE="$(./scripts/resolve-profile.sh)"
PRIVATE_DIR="${MAC_BOOTSTRAP_PRIVATE_DIR:-}"
if [[ -z "$PRIVATE_DIR" || ! -d "$PRIVATE_DIR" ]]; then
  if [[ -d "$REPO_ROOT/../private" ]]; then
    PRIVATE_DIR="$(cd "$REPO_ROOT/../private" && pwd)"
  else
    PRIVATE_DIR="$REPO_ROOT/private"
  fi
fi
PROXY_ENV="$PRIVATE_DIR/profiles/$PROFILE/proxy.env"
PROXY_PORT=""
if [[ -r "$PROXY_ENV" ]]; then
  PROXY_PORT="$(sed -n 's/^PROXY_PORT=//p' "$PROXY_ENV")"
fi
if [[ "$PROXY_PORT" =~ ^[0-9]{1,5}$ ]] && ((PROXY_PORT >= 1 && PROXY_PORT <= 65535)); then
  HEALTH_PROXY_ARGS=(--proxy "http://127.0.0.1:$PROXY_PORT" --noproxy "localhost,127.0.0.1,::1")
else
  HEALTH_PROXY_ARGS=(--noproxy '*')
fi

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
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "${HEALTH_PROXY_ARGS[@]}" "$PUBLIC_MCP_URL" 2>/dev/null || echo 000)"
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
