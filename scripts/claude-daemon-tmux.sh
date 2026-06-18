#!/usr/bin/env bash
# Claude Code keepalive daemon — macOS launchd-managed
# Sends a non-interactive claude -p ping on a calendar schedule (00:00 / 08:00 / 15:00).
# Override defaults via env vars (set in ~/.zshrc.local or private overlay):
#   CLAUDE_PROJECT_DIR  — working directory for claude (default: $HOME/work)
#   CLAUDE_SESSION      — unused; kept for forward compat
#   CLAUDE_TIMEOUT      — seconds before force-killing claude (default: 60)
set -uo pipefail  # no -e: we handle errors explicitly below

# --- config ---
export PATH="${CLAUDE_BIN_EXTRA_PATH:+${CLAUDE_BIN_EXTRA_PATH}:}/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$HOME/work}"
CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-60}"  # seconds; override via env if needed

LOG_DIR="${HOME}/Library/Logs/claude-daemon"
LOG="${LOG_DIR}/tmux.log"
mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# --- lock: prevent overlapping runs ---
LOCK_FILE="/tmp/claude-daemon.lock"
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null || true)
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        log "SKIP: another instance running (PID $LOCK_PID)"
        exit 0
    fi
    log "WARN: removing stale lock (PID $LOCK_PID)"
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# run_with_timeout <seconds> cmd [args...]
# Kills the entire process group on timeout (SIGTERM → SIGKILL after 5 s).
# The watchdog subshell immediately closes inherited FDs (exec >/dev/null 2>&1)
# so orphaned sleeps inside it never hold the caller's stdout/stderr pipes open.
run_with_timeout() {
    local timeout_secs="$1"; shift

    # Spawn the command in its own session so timeout signals can target the
    # whole process group without touching this wrapper shell.
    python3 - "$@" <<'PY' &
import os
import sys

os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])
PY
    local child_pid=$!
    local child_pgid="$child_pid"

    (
        exec >/dev/null 2>&1          # close inherited pipes — critical for correctness
        sleep "$timeout_secs"
        if kill -0 "$child_pid" 2>/dev/null; then
            log "TIMEOUT: claude -p exceeded ${timeout_secs}s — SIGTERM pid $child_pid"
            kill -TERM -- "-$child_pgid" 2>/dev/null || true
            sleep 5
            if kill -0 "$child_pid" 2>/dev/null; then
                log "TIMEOUT: still alive after SIGTERM — SIGKILL pid $child_pid"
                kill -KILL -- "-$child_pgid" 2>/dev/null || true
            fi
        fi
    ) &
    local watchdog_pid=$!

    wait "$child_pid" 2>/dev/null
    local exit_status=$?

    kill "$watchdog_pid" 2>/dev/null || true
    wait "$watchdog_pid" 2>/dev/null || true

    return $exit_status
}

# --- main: keepalive ping via claude -p ---
START_TS=$(date '+%s')
log "=== tmux daemon starting ==="
log "  project_dir: $CLAUDE_PROJECT_DIR"
log "  timeout: ${CLAUDE_TIMEOUT}s"
log "Sending keepalive via claude -p"

cd "$CLAUDE_PROJECT_DIR"
run_with_timeout "$CLAUDE_TIMEOUT" \
    claude -p "# keepalive: $(date '+%Y-%m-%d %H:%M:%S')" --bare --no-session-persistence \
    2>/dev/null
EXIT_STATUS=$?

ELAPSED=$(( $(date '+%s') - START_TS ))
if [ "$EXIT_STATUS" -eq 0 ]; then
    log "=== claude keepalive finished (${ELAPSED}s, exit 0) ==="
else
    log "=== claude keepalive finished (${ELAPSED}s, exit ${EXIT_STATUS}) ==="
fi
