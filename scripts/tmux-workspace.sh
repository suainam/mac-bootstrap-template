#!/usr/bin/env bash
set -euo pipefail

SESSION="${1:-${TMUX_SESSION:-ai-work}}"
WORKDIR="${TMUX_WORKDIR:-$HOME/work}"
DAEMON_WINDOW="${TMUX_DAEMON_WINDOW:-_daemon_}"
ANALYSIS_WINDOW="${TMUX_ANALYSIS_WINDOW:-analysis}"

set_pane_title() {
  local target="$1"
  local title="$2"
  tmux select-pane -t "$target" -T "$title"
}

create_analysis_window() {
  tmux new-window -t "$SESSION" -n "$ANALYSIS_WINDOW" -c "$WORKDIR" /bin/zsh -l
  tmux split-window -h -t "$SESSION:$ANALYSIS_WINDOW.0" -p 50 -c "$WORKDIR" /bin/zsh -l
  tmux split-window -v -t "$SESSION:$ANALYSIS_WINDOW.0" -p 50 -c "$WORKDIR" /bin/zsh -l
  tmux split-window -v -t "$SESSION:$ANALYSIS_WINDOW.1" -p 50 -c "$WORKDIR" /bin/zsh -l
  tmux select-layout -t "$SESSION:$ANALYSIS_WINDOW" tiled

  set_pane_title "$SESSION:$ANALYSIS_WINDOW.0" "shell"
  set_pane_title "$SESSION:$ANALYSIS_WINDOW.1" "python"
  set_pane_title "$SESSION:$ANALYSIS_WINDOW.2" "sql"
  set_pane_title "$SESSION:$ANALYSIS_WINDOW.3" "notes"
}

if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach -t "$SESSION"
fi

tmux new-session -d -s "$SESSION" -n "$DAEMON_WINDOW" -c "$WORKDIR" \
  /bin/zsh -lc 'if command -v codex >/dev/null 2>&1; then codex; fi; exec zsh -l'
tmux split-window -h -t "$SESSION:$DAEMON_WINDOW.0" -p 50 -c "$WORKDIR" /bin/zsh -l
tmux split-window -v -t "$SESSION:$DAEMON_WINDOW.0" -p 50 -c "$WORKDIR" /bin/zsh -l

create_analysis_window

# Pane 标题（显示在边框顶部）
# split -h 产生右侧 pane (1), split -v 产生左下 pane (2)
set_pane_title "$SESSION:$DAEMON_WINDOW.0" "daemon"
set_pane_title "$SESSION:$DAEMON_WINDOW.1" "shell"
set_pane_title "$SESSION:$DAEMON_WINDOW.2" "notes"

tmux select-pane -t "$SESSION:$DAEMON_WINDOW.1"
tmux select-window -t "$SESSION:$ANALYSIS_WINDOW"
exec tmux attach -t "$SESSION"
