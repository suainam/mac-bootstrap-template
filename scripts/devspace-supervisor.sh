#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# 隧道入口(cloudflared/CF)会附加 X-Forwarded-For；不信任它时 express-rate-limit
# 校验会直接抛 ERR_ERL_UNEXPECTED_X_FORWARDED_FOR 杀死进程，故必须开启
export DEVSPACE_TRUST_PROXY=true
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
  stop_child
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

cleanup_stale_port_holders() {
  local port_pids
  port_pids="$(lsof -ti tcp:7676 2>/dev/null || true)"
  if [[ -n "$port_pids" ]]; then
    log "cleaning up stale processes occupying port 7676: $port_pids"
    echo "$port_pids" | xargs kill -TERM 2>/dev/null || true
    sleep 1
    # 强制清理未响应 TERM 的僵死残留
    local remaining
    remaining="$(lsof -ti tcp:7676 2>/dev/null || true)"
    if [[ -n "$remaining" ]]; then
      echo "$remaining" | xargs kill -9 2>/dev/null || true
    fi
  fi
}

start_child() {
  cd "$REPO_ROOT"
  ./scripts/devspace-local.sh check
  cleanup_stale_port_holders
  log "starting devspace"
  ./scripts/devspace-local.sh run &
  child_pid="$!"
}

stop_child() {
  if [[ -n "$child_pid" ]]; then
    log "stopping devspace process tree for pid $child_pid"
    # 向负 PID 广播信号，确保子进程树（devspace_local.py 与 node serve）一同接收退出信号
    kill -TERM -"$child_pid" 2>/dev/null || kill -TERM "$child_pid" 2>/dev/null || true
    
    # 优雅等待最多 5 秒
    local count=0
    while kill -0 "$child_pid" 2>/dev/null && (( count < 5 )); do
      sleep 1
      count=$((count + 1))
    done
    
    # 仍未退出的强制杀灭
    if kill -0 "$child_pid" 2>/dev/null; then
      kill -9 -"$child_pid" 2>/dev/null || kill -9 "$child_pid" 2>/dev/null || true
    fi
    wait "$child_pid" 2>/dev/null || true
  fi
  child_pid=""
  cleanup_stale_port_holders
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
