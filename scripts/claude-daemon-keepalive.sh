#!/usr/bin/env bash
# ⚠️  DEPRECATED — 2026-06-11
# This service is intentionally disabled.
# Reason: user decided keepalive is unnecessary; Claude cache TTL
# is handled by active usage, not background pings.
# DO NOT re-enable this launchd service.
# Plist moved to: ~/.local/share/mackup/.../io.local.mac-bootstrap.claude-keepalive.plist.disabled
#
# Claude Code keepalive — zellij backend
# Periodically sends a cache_check to the zellij Claude pane to prevent
# Claude's 300s cache TTL from expiring during active work periods.
#
# Override defaults via env vars:
#   ZELLIJ_SESSION         — zellij session name (default: ai-work)
#   CLAUDE_THRESHOLD       — idle seconds before sending (default: 230)
#   CLAUDE_WORK_WINDOWS    — comma-separated windows (default: 09:00-12:30,13:30-18:30)
#   CLAUDE_ACTIVE_MAX_IDLE — stop pinging after this much inactivity (default: 5400)
#
# Safety: threshold(230) + interval(60) = 290 < cache_TTL(300) = 10s margin
# Unset ZELLIJ to avoid socket discovery issues when run outside zellij.
unset ZELLIJ 2>/dev/null || true
set -euo pipefail

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SESSION="${ZELLIJ_SESSION:-ai-work}"
THRESHOLD="${CLAUDE_THRESHOLD:-230}"
WORK_WINDOWS="${CLAUDE_WORK_WINDOWS:-09:00-12:30,13:30-18:30}"
ACTIVE_MAX_IDLE="${CLAUDE_ACTIVE_MAX_IDLE:-5400}"

LOG_DIR="${HOME}/Library/Logs/claude-daemon"
LOG="${LOG_DIR}/keepalive.log"
mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

# ── work-hours gate ──────────────────────────────────────────────
to_minutes() {
    local hhmm="$1"
    local hour="${hhmm%:*}"
    local minute="${hhmm#*:}"
    echo $((10#$hour * 60 + 10#$minute))
}

in_work_window() {
    local weekday now range start end
    weekday="$(date +%u)"
    [ "$weekday" -le 5 ] || return 1

    now=$((10#$(date +%H) * 60 + 10#$(date +%M)))
    IFS=',' read -r -a ranges <<< "$WORK_WINDOWS"
    for range in "${ranges[@]}"; do
        start="${range%-*}"
        end="${range#*-}"
        if [ "$now" -ge "$(to_minutes "$start")" ] && [ "$now" -le "$(to_minutes "$end")" ]; then
            return 0
        fi
    done
    return 1
}

in_work_window || exit 0

# ── zellij wrapper (clean env for socket discovery) ──────────────
zj() {
    env -i HOME="$HOME" PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" \
        TERM="${TERM:-xterm}" \
        /opt/homebrew/bin/zellij "$@"
}

# ── verify zellij session + claude pane ──────────────────────────
if ! zj --session "$SESSION" action list-panes --json >/dev/null 2>&1; then
    log "WAIT zellij session $SESSION not reachable (no attached client?)"
    exit 0
fi

PANE_ID=$(zj --session "$SESSION" action list-panes --json 2>/dev/null |
    jq -r '[ .[] | select(
        (.is_plugin == false) and
        (.terminal_command == "claude") and
        (.exited == false)
    ) ] | first | .id // empty' 2>/dev/null)

[ -n "$PANE_ID" ] || { log "WAIT no claude pane in session $SESSION"; exit 0; }

# ── calculate idle time from jsonl ───────────────────────────────
LATEST_JSONL=$(find "${HOME}/.claude/projects" -maxdepth 3 -name '*.jsonl' \
    -exec stat -f '%m %N' {} \; 2>/dev/null | sort -rn | head -1)
LAST_MSG=$(echo "$LATEST_JSONL" | awk '{print $1}')
LAST_PROJECT=$(echo "$LATEST_JSONL" | awk '{print $2}' | sed 's|.*/projects/||; s|/[^/]*$||')

if [ -z "$LAST_MSG" ]; then
    log "WARN: no jsonl found, sending cache_check anyway"
    IDLE=999
else
    IDLE=$(( $(date +%s) - LAST_MSG ))
fi

if [ "$IDLE" -gt "$ACTIVE_MAX_IDLE" ]; then
    log "SKIP idle ${IDLE}s exceeds active window ${ACTIVE_MAX_IDLE}s"
    exit 0
fi

if [ "$IDLE" -ge "$THRESHOLD" ]; then
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    if zj --session "$SESSION" action write-chars -p "$PANE_ID" "# cache_check: $TIMESTAMP" 2>/dev/null &&
       zj --session "$SESSION" action send-keys -p "$PANE_ID" Enter 2>/dev/null; then
        log "SENT cache_check at $TIMESTAMP (idle ${IDLE}s, pane $PANE_ID, last_project: ${LAST_PROJECT:-none})"
    else
        log "ERROR: failed to write to pane $PANE_ID (idle ${IDLE}s)"
        exit 1
    fi
fi
