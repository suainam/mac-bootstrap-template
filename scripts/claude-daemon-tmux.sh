#!/usr/bin/env bash
# Claude Code tmux daemon — macOS launchd-managed
# Keeps a tmux session alive with Claude Code running in a dedicated pane.
# Override defaults via env vars (set in ~/.zshrc.local or private overlay):
#   CLAUDE_PROJECT_DIR  — project directory for claude (default: $HOME/work)
#   CLAUDE_SESSION      — tmux session name (default: _daemon_)
#   CLAUDE_PANE_TITLE   — tmux pane title (default: claude-keepalive)
set -euo pipefail

# launchd runs with minimal PATH; ensure Homebrew & local bin are available
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$HOME/work}"
SESSION="${CLAUDE_SESSION:-_daemon_}"
PANE_TITLE="${CLAUDE_PANE_TITLE:-claude-keepalive}"

LOG_DIR="${HOME}/Library/Logs/claude-daemon"
LOG="${LOG_DIR}/tmux.log"
mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

log "=== tmux daemon starting ==="
log "  project_dir: $CLAUDE_PROJECT_DIR"
log "  session: $SESSION"

ensure_tmux_server() {
    if ! tmux info &>/dev/null 2>&1; then
        log "tmux server not running, starting server"
        TMUX= tmux start-server
        sleep 1
    fi
}

# Get the daemon-managed pane ID by fixed index (session:window.pane)
get_pane_id() {
    tmux list-panes -t "$SESSION:1.0" -F '#{pane_id}' 2>/dev/null | head -1
}

get_pane_cmd() {
    local pid="$1"
    tmux display-message -p -t "$pid" '#{pane_current_command}' 2>/dev/null || echo ""
}

# Send the claude command to the given pane (no restart loop — outer health check handles recovery)
start_claude_in_pane() {
    local pid="$1"
    log "Starting claude in pane $pid"
    tmux send-keys -t "$pid" \
        "cd '$CLAUDE_PROJECT_DIR' && claude \"# session started: \$(date '+%Y-%m-%d %H:%M:%S')\"" Enter
    sleep 0.5
    tmux select-pane -t "$pid" -T "$PANE_TITLE"
    tmux set-option -p -t "$pid" allow-rename off
    log "claude started with title $PANE_TITLE (allow-rename off)"
}

ensure_claude_session() {
    local pid

    # Create session if it does not exist
    if ! tmux has-session -t "$SESSION" 2>/dev/null; then
        log "Creating $SESSION session with daemon pane (cwd: $CLAUDE_PROJECT_DIR)"
        TMUX= tmux new-session -d -s "$SESSION" -c "$CLAUDE_PROJECT_DIR"

        # Get first pane
        pid=$(tmux list-panes -t "$SESSION" -F '#{pane_id}' 2>/dev/null | head -1)
        if [ -z "$pid" ]; then
            log "ERROR: no pane found after creating session"
            return 1
        fi

        start_claude_in_pane "$pid"
        return 0
    fi

    # Session exists — check daemon pane (window 1, pane 0)
    pid="$(get_pane_id)"
    if [ -z "$pid" ]; then
        log "ERROR: daemon pane $_daemon_:1.0 not found, rebuilding session"
        tmux kill-session -t "$SESSION" 2>/dev/null || true
        sleep 1
        ensure_claude_session
        return $?
    fi

    # Check if claude is already running in the pane
    local pane_cmd
    pane_cmd="$(get_pane_cmd "$pid")"
    if [ "$pane_cmd" = "claude" ]; then
        return 0
    fi

    log "Pane $pid running '$pane_cmd' instead of claude, restarting"
    start_claude_in_pane "$pid"
}

HEALTH_CHECK_INTERVAL=600
LAST_HEALTH_CHECK=$(date +%s)

while true; do
    pid=""
    pane_cmd=""
    ensure_tmux_server
    ensure_claude_session

    NOW=$(date +%s)
    if [ $(( NOW - LAST_HEALTH_CHECK )) -ge $HEALTH_CHECK_INTERVAL ]; then
        pid="$(get_pane_id)"
        pane_cmd="unknown"
        [ -n "$pid" ] && pane_cmd=$(tmux display-message -p -t "$pid" '#{pane_current_command}' 2>/dev/null || echo "unknown")
        log "HEALTH_CHECK: session=${SESSION} pane=${pid:-none} cmd=${pane_cmd}"
        LAST_HEALTH_CHECK=$NOW
    fi

    sleep 30
done
