#!/usr/bin/env bash
# Claude Code keepalive — macOS launchd-timer
# Periodically sends a comment to the tmux pane to prevent Claude's
# 300s cache TTL from expiring during idle periods.
# Override defaults via env vars (set in ~/.zshrc.local or private overlay):
#   CLAUDE_SESSION    — tmux session name (default: _daemon_)
#   CLAUDE_THRESHOLD  — idle seconds before sending cache_check (default: 230)
#   CLAUDE_PROJECT_DIR — project directory (default: $HOME/work)
#
# Safety: threshold(230) + timer_interval(60) = 290 < cache_TTL(300) = 10s margin
set -euo pipefail

# launchd runs with minimal PATH; ensure Homebrew & local bin are available
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SESSION="${CLAUDE_SESSION:-_daemon_}"
THRESHOLD="${CLAUDE_THRESHOLD:-230}"

LOG_DIR="${HOME}/Library/Logs/claude-daemon"
LOG="${LOG_DIR}/keepalive.log"
mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

# Working hours: 8:00~19:00 or 23:30~00:30
HOUR=$(date +%H)
MIN=$(date +%M)
if ! ( \
    ([ "$HOUR" -ge 8 ] && [ "$HOUR" -lt 19 ]) \
    || ([ "$HOUR" -eq 23 ] && [ "$MIN" -ge 30 ]) \
    || ([ "$HOUR" -eq 0 ] && [ "$MIN" -le 30 ]) \
); then
    exit 0
fi

# Find latest jsonl activity across all claude projects
LATEST_JSONL=$(find "${HOME}/.claude/projects" -maxdepth 3 -name '*.jsonl' \
    -exec stat -f '%m %N' {} \; 2>/dev/null | sort -rn | head -1)
LAST_MSG=$(echo "$LATEST_JSONL" | awk '{print $1}')
LAST_PROJECT=$(echo "$LATEST_JSONL" | awk '{print $2}' | sed 's|.*/projects/||; s|/[^/]*$||')

# Verify tmux session and pane exist
tmux has-session -t "$SESSION" 2>/dev/null || { log "ERROR: session $SESSION not found"; exit 1; }
PANE_ID=$(tmux list-panes -t "$SESSION" -F '#{pane_id}' 2>/dev/null | head -1)
[ -z "$PANE_ID" ] && { log "ERROR: no pane found in session $SESSION"; exit 1; }

# Calculate idle time
if [ -z "$LAST_MSG" ]; then
    log "WARN: no jsonl found, sending cache_check anyway"
    IDLE=999
else
    IDLE=$(( $(date +%s) - LAST_MSG ))
fi

if [ "$IDLE" -ge "$THRESHOLD" ]; then
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    if tmux send-keys -t "$PANE_ID" "# cache_check: $TIMESTAMP" Enter 2>/dev/null; then
        log "SENT cache_check at $TIMESTAMP (idle ${IDLE}s, pane $PANE_ID, last_project: ${LAST_PROJECT:-none})"
    else
        log "ERROR: failed to send to $PANE_ID (idle ${IDLE}s, last_project: ${LAST_PROJECT:-none})"
        exit 1
    fi
fi
