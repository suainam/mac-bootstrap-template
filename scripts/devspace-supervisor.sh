#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

HEALTHY_CODES="200 400 401 405"
STARTUP_TIMEOUT_SECONDS=180
CHECK_INTERVAL_SECONDS=30
MAX_FAILURES=3

child_pid=""

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

terminate() {
  log "terminating devspace supervisor"
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" >/dev/null 2>&1; then
    kill "$child_pid" >/dev/null 2>&1 || true
    wait "$child_pid" >/dev/null 2>&1 || true
  fi
  exit 0
}

trap terminate TERM INT

is_healthy_code() {
  local code="$1"
  local healthy
  for healthy in $HEALTHY_CODES; do
    if [[ "$code" == "$healthy" ]]; then
      return 0
    fi
  done
  return 1
}

probe_mcp() {
  curl -sS -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:7676/mcp" 2>/dev/null || true
}

wait_for_startup() {
  local deadline code
  deadline=$((SECONDS + STARTUP_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    code="$(probe_mcp)"
    if is_healthy_code "$code"; then
      log "devspace /mcp healthy with HTTP $code"
      return 0
    fi
    sleep 2
  done
  log "devspace did not become healthy within ${STARTUP_TIMEOUT_SECONDS}s"
  return 1
}

start_child() {
  cd "$REPO_ROOT"
  ./scripts/devspace-local.sh check
  log "starting devspace"
  ./scripts/devspace-local.sh run &
  child_pid="$!"
}

stop_child() {
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" >/dev/null 2>&1; then
    log "stopping devspace child pid $child_pid"
    kill "$child_pid" >/dev/null 2>&1 || true
    wait "$child_pid" >/dev/null 2>&1 || true
  fi
  child_pid=""
}

main() {
  local failures code
  failures=0

  start_child
  wait_for_startup || {
    stop_child
    exit 1
  }

  while true; do
    if [[ -n "$child_pid" ]] && ! kill -0 "$child_pid" >/dev/null 2>&1; then
      log "devspace child exited"
      wait "$child_pid" >/dev/null 2>&1 || true
      child_pid=""
      exit 1
    fi

    code="$(probe_mcp)"
    if is_healthy_code "$code"; then
      failures=0
    else
      failures=$((failures + 1))
      log "devspace health probe failed with HTTP ${code:-none}; failure $failures/$MAX_FAILURES"
    fi

    if (( failures >= MAX_FAILURES )); then
      log "restarting devspace after $MAX_FAILURES failed probes"
      stop_child
      start_child
      wait_for_startup || {
        stop_child
        exit 1
      }
      failures=0
    fi

    sleep "$CHECK_INTERVAL_SECONDS"
  done
}

main "$@"
