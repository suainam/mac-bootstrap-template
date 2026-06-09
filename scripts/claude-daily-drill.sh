#!/usr/bin/env bash
# Inject one daily Claude battle drill into the Zellij Claude pane.
set -euo pipefail

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SESSION="${ZELLIJ_SESSION:-${CLAUDE_SESSION:-ai-work}}"
LAYOUT="${ZELLIJ_DEFAULT_LAYOUT:-ai-work}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$HOME/work}"
SKILL_NAME="${CLAUDE_DAILY_SKILL_NAME:-daily-claude-battle-boost}"
TARGET_TIME="${CLAUDE_DAILY_TARGET_TIME:-09:35}"
LAST_RUN_FILE="${CLAUDE_DAILY_LAST_RUN_FILE:-$HOME/Library/Application Support/claude-daemon/daily-drill.last}"
FORCE_RUN="${CLAUDE_DAILY_FORCE:-0}"
EXPORT_SCRIPT="${CLAUDE_DAILY_EXPORT_SCRIPT:-$HOME/work/config/mac-bootstrap/template/scripts/claude-daily-drill-export.sh}"
BACKEND="${CLAUDE_DAILY_BACKEND:-zellij}"
LOG_DIR="${HOME}/Library/Logs/claude-daemon"
LOG="${LOG_DIR}/daily-drill.log"
mkdir -p "$LOG_DIR" "$(dirname "$LAST_RUN_FILE")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

get_pane_id() {
    tmux list-panes -t "$SESSION:1.0" -F '#{pane_id}' 2>/dev/null | head -1
}

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

ensure_zellij_session() {
    if zellij --session "$SESSION" action list-panes --json >/dev/null 2>&1; then
        return 0
    fi

    zellij attach --create-background "$SESSION" options --default-layout "$LAYOUT" >/dev/null 2>&1 || true
    sleep 1
}

get_zellij_pane_id() {
    zellij --session "$SESSION" action list-panes --json -c -s -t 2>/dev/null |
        jq -r '
          .. | objects
          | select((.command? == "claude") and (((.state? // "") | tostring | ascii_downcase) != "exited"))
          | (.pane_id // .id // empty)
        ' | head -1
}

ensure_tmux_session() {
    tmux has-session -t "$SESSION" 2>/dev/null
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

spawn_exporter() {
    local today
    today="$(date '+%Y-%m-%d')"
    if [ -x "$EXPORT_SCRIPT" ]; then
        (
            "$EXPORT_SCRIPT" --date "$today" >/dev/null 2>&1
        ) &
        disown || true
    else
        log "WARN export script not executable: $EXPORT_SCRIPT"
    fi
}

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

main() {
    if [ "$FORCE_RUN" != "1" ]; then
        due_now || exit 0
        already_ran_today && exit 0
    fi

    local pane_id prompt
    prompt="$(build_prompt)"

    case "$BACKEND" in
        zellij)
            if ! command -v zellij >/dev/null 2>&1; then
                log "WAIT zellij not found"
                exit 0
            fi

            ensure_zellij_session
            pane_id="$(get_zellij_pane_id)"
            [ -n "$pane_id" ] || { log "WAIT no claude pane found in session $SESSION"; exit 0; }

            zellij --session "$SESSION" action paste --pane-id "$pane_id" "$prompt"
            zellij --session "$SESSION" action send-keys --pane-id "$pane_id" Enter
            ;;
        tmux)
            tmux has-session -t "$SESSION" 2>/dev/null || { log "WAIT session $SESSION not found"; exit 0; }

            pane_id="$(get_pane_id)"
            [ -n "$pane_id" ] || { log "WAIT no pane found in session $SESSION"; exit 0; }

            local pane_cmd
            pane_cmd="$(tmux display-message -p -t "$pane_id" '#{pane_current_command}' 2>/dev/null || echo "")"
            [ "$pane_cmd" = "claude" ] || { log "WAIT pane $pane_id is running '$pane_cmd'"; exit 0; }

            tmux set-buffer -- "$prompt"
            tmux paste-buffer -t "$pane_id"
            tmux send-keys -t "$pane_id" Enter
            ;;
        *)
            log "WAIT unsupported backend $BACKEND"
            exit 0
            ;;
    esac

    mark_ran_today
    spawn_exporter

    log "SENT daily drill to ${pane_id} via ${BACKEND} (focus: $(get_focus_label), skill: ${SKILL_NAME}, force=${FORCE_RUN})"
}

main "$@"
