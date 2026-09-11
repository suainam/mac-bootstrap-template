#!/usr/bin/env bash
# Claude Code keepalive daemon — macOS launchd-managed
# Sends a non-interactive claude -p ping on a calendar schedule (00:00 / 08:00 / 15:00).
# launchd captures stdout/stderr in /tmp/claude-daemon-tmux.{log,err}, while
# this script appends structured run summaries to ~/Library/Logs/claude-daemon/tmux.log.
# Override defaults via env vars (set in ~/.zshrc.local or private overlay):
#   CLAUDE_PROJECT_DIR  — working directory for claude (default: $HOME/work)
#   CLAUDE_SESSION      — unused; kept for forward compat
#   CLAUDE_TIMEOUT      — seconds before force-killing claude (default: 60)
#   CLAUDE_KEEPALIVE_PROMPT — override the default keepalive prompt for drills/tests
#   CLAUDE_KEEPALIVE_PROMPT_FILE — file path for multi-line prompt overrides
set -uo pipefail  # no -e: we handle errors explicitly below

# --- config ---
export PATH="${CLAUDE_BIN_EXTRA_PATH:+${CLAUDE_BIN_EXTRA_PATH}:}/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$HOME/work}"
CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-60}"  # seconds; override via env if needed
CLAUDE_KEEPALIVE_PROMPT_FILE="${CLAUDE_KEEPALIVE_PROMPT_FILE:-}"
PROMPT_SOURCE="default"
CLAUDE_KEEPALIVE_PROMPT="${CLAUDE_KEEPALIVE_PROMPT:-# keepalive: $(date '+%Y-%m-%d %H:%M:%S')}"
DEFAULT_PROMPT_FILE="${HOME}/.claude/claude-daemon-prompt.txt"

if [ -n "$CLAUDE_KEEPALIVE_PROMPT_FILE" ] && [ -r "$CLAUDE_KEEPALIVE_PROMPT_FILE" ]; then
    CLAUDE_KEEPALIVE_PROMPT="$(cat "$CLAUDE_KEEPALIVE_PROMPT_FILE")"
    PROMPT_SOURCE="file:$CLAUDE_KEEPALIVE_PROMPT_FILE"
elif [ -r "$DEFAULT_PROMPT_FILE" ]; then
    CLAUDE_KEEPALIVE_PROMPT="$(cat "$DEFAULT_PROMPT_FILE")"
    PROMPT_SOURCE="file:$DEFAULT_PROMPT_FILE"
elif [ -n "${CLAUDE_KEEPALIVE_PROMPT:-}" ]; then
    PROMPT_SOURCE="env"
fi

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

# kill_tree <pid> [signal]
# Recursively kill a process and every descendant, regardless of process group.
# Real `claude -p` spawns helper processes that may re-parent into their own
# session, so a process-group kill alone can leave orphans that keep the parent
# alive far past the deadline (observed: 28 min runs at the 08:00 slot).
kill_tree() {
    local target="$1"
    local signal="${2:-TERM}"
    local descendants
    descendants="$(pgrep -P "$target" 2>/dev/null || true)"
    for pid in $descendants; do
        kill_tree "$pid" "$signal" 2>/dev/null || true
    done
    kill -"$signal" -- "-$target" 2>/dev/null || true   # process group
    kill -"$signal" "$target" 2>/dev/null || true        # explicit PID
}

# kill_tree_rescan <target> <signal>
# A helper can fork a fresh descendant *after* the first scan, so the SIGTERM
# pass must be re-run before SIGKILL — otherwise a respawning child survives both.
kill_tree_rescan() {
    local target="$1"
    local signal="${2:-TERM}"
    local descendants
    descendants="$(pgrep -P "$target" 2>/dev/null || true)"
    for pid in $descendants; do
        kill_tree "$pid" "$signal" 2>/dev/null || true
    done
    kill -"$signal" -- "-$target" 2>/dev/null || true
    kill -"$signal" "$target" 2>/dev/null || true
}

run_with_timeout() {
    local timeout_secs="${1:-$CLAUDE_TIMEOUT}"
    local grace_secs="${CLAUDE_KILL_GRACE:-3}"
    shift

    "$@" &
    local child_pid=$!
    local child_pgid="$child_pid"

    (
        exec >/dev/null 2>&1          # close inherited pipes — critical for correctness
        sleep "$timeout_secs"
        if kill -0 "$child_pid" 2>/dev/null; then
            log "TIMEOUT: claude -p exceeded ${timeout_secs}s — SIGTERM pid $child_pid"
            kill_tree_rescan "$child_pgid" TERM
            sleep "$grace_secs"
            if kill -0 "$child_pid" 2>/dev/null; then
                log "TIMEOUT: still alive after SIGTERM — SIGKILL pid $child_pid"
                kill_tree_rescan "$child_pgid" KILL
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
log "  prompt_source: $PROMPT_SOURCE"
log "Sending keepalive via claude -p"

cd "$CLAUDE_PROJECT_DIR"
run_with_timeout "$CLAUDE_TIMEOUT" \
    claude -p "$CLAUDE_KEEPALIVE_PROMPT" --bare --no-session-persistence
EXIT_STATUS=$?

ELAPSED=$(( $(date '+%s') - START_TS ))
if [ "$EXIT_STATUS" -eq 0 ]; then
    log "=== claude keepalive finished (${ELAPSED}s, exit 0) ==="
else
    log "=== claude keepalive finished (${ELAPSED}s, exit ${EXIT_STATUS}) ==="
fi
