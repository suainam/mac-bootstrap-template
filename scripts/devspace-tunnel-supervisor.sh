#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

cd "$REPO_ROOT"

log "validating Cloudflare Tunnel configuration; token output stays <redacted>"
./scripts/devspace-local.sh --dry-run tunnel-run >/dev/null

log "starting Cloudflare Tunnel with token <redacted>"
exec ./scripts/devspace-local.sh tunnel-run
