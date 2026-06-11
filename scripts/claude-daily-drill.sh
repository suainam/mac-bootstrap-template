#!/usr/bin/env bash
# Inject one daily Claude battle drill into the Zellij Claude pane.
# Unset ZELLIJ to avoid socket discovery issues when run outside zellij.
unset ZELLIJ 2>/dev/null || true
set -euo pipefail

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SESSION="${ZELLIJ_SESSION:-ai-work}"
LAYOUT="${ZELLIJ_DEFAULT_LAYOUT:-ai-work}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$HOME/work}"
SKILL_NAME="${CLAUDE_DAILY_SKILL_NAME:-daily-claude-battle-boost}"
TARGET_TIME="${CLAUDE_DAILY_TARGET_TIME:-09:35}"
LAST_RUN_FILE="${CLAUDE_DAILY_LAST_RUN_FILE:-$HOME/Library/Application Support/claude-daemon/daily-drill.last}"
FORCE_RUN="${CLAUDE_DAILY_FORCE:-0}"
LOG_DIR="${HOME}/Library/Logs/claude-daemon"
LOG="${LOG_DIR}/daily-drill.log"
mkdir -p "$LOG_DIR" "$(dirname "$LAST_RUN_FILE")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

# ── helpers ──────────────────────────────────────────────────────
get_focus_label() {
    case "$(date +%u)" in
        1) echo "驾驭力" ;;
        2) echo "效率感" ;;
        3) echo "产出力" ;;
        4) echo "探索欲" ;;
        5) echo "综合实战" ;;
        *) echo "复盘+补短板" ;;
    esac
}

to_minutes() {
    local hhmm="$1"
    local hour="${hhmm%:*}"
    local minute="${hhmm#*:}"
    echo $((10#$hour * 60 + 10#$minute))
}

already_ran_today() {
    [ -f "$LAST_RUN_FILE" ] && [ "$(cat "$LAST_RUN_FILE" 2>/dev/null)" = "$(date '+%Y-%m-%d')" ]
}

due_now() {
    local now target
    now=$((10#$(date +%H) * 60 + 10#$(date +%M)))
    target="$(to_minutes "$TARGET_TIME")"
    [ "$now" -ge "$target" ]
}

mark_ran_today() {
    date '+%Y-%m-%d' > "$LAST_RUN_FILE"
}

# ── zellij wrapper (clean env for socket discovery) ──────────────
# Some env vars in the user's shell interfere with zellij's socket
# discovery. Running zellij action commands in a clean env avoids this.
zj() {
    env -i HOME="$HOME" PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" \
        TERM="${TERM:-xterm}" \
        /opt/homebrew/bin/zellij "$@"
}

# ── zellij pane detection ────────────────────────────────────────
ensure_zellij_session() {
    if zj --session "$SESSION" action list-panes --json >/dev/null 2>&1; then
        return 0
    fi
    zj --session "$SESSION" --layout "$LAYOUT" 2>/dev/null &
    disown || true
    sleep 2
    zj --session "$SESSION" action list-panes --json >/dev/null 2>&1
}

get_claude_pane_id() {
    zj --session "$SESSION" action list-panes --json 2>/dev/null |
        jq -r '
          [ .[] | select(
            (.is_plugin == false) and
            (.terminal_command == "claude") and
            (.exited == false)
          ) ] | first | .id // empty
        ' 2>/dev/null
}

# ── prompt ───────────────────────────────────────────────────────
build_prompt() {
    local today focus
    today="$(date '+%Y-%m-%d')"
    focus="$(get_focus_label)"
    cat <<EOF
Use the \`${SKILL_NAME}\` skill to run today's drill.

Date: ${today}
Primary focus: ${focus}
Workspace: ${PROJECT_DIR}

Requirements:
1. Produce one concise daily drill card.
2. Prefer a realistic work task over a fake exercise.
3. Output exactly these sections:
   - Today's target dimension
   - Why this dimension today
   - Main prompt
   - Follow-up prompt
   - Reflection prompt
   - One scorekeeping tip
4. Keep the whole answer compact but actionable.
EOF
}

# ── main ─────────────────────────────────────────────────────────
main() {
    if [ "$FORCE_RUN" != "1" ]; then
        due_now || exit 0
        already_ran_today && exit 0
    fi

    if ! command -v zellij >/dev/null 2>&1; then
        log "WAIT zellij not found"
        exit 0
    fi

    ensure_zellij_session || { log "WAIT cannot reach zellij session $SESSION"; exit 0; }

    local pane_id
    pane_id="$(get_claude_pane_id)"
    [ -n "$pane_id" ] || { log "WAIT no claude pane found in session $SESSION"; exit 0; }

    local prompt
    prompt="$(build_prompt)"

    zj --session "$SESSION" action write-chars -p "$pane_id" "$prompt"
    zj --session "$SESSION" action send-keys -p "$pane_id" Enter

    mark_ran_today

    log "SENT daily drill to pane $pane_id (focus: $(get_focus_label), skill: ${SKILL_NAME}, force=${FORCE_RUN})"
}

main "$@"
