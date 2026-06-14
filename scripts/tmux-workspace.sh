#!/usr/bin/env bash
set -euo pipefail

SESSION="${1:-${TMUX_SESSION:-ai-work}}"
WORKDIR="${TMUX_WORKDIR:-$HOME/work}"
DAEMON_WINDOW="${TMUX_DAEMON_WINDOW:-_daemon_}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach -t "$SESSION"
fi

tmux new-session -d -s "$SESSION" -n "$DAEMON_WINDOW" -c "$WORKDIR" \
  /bin/zsh -lc 'if command -v codex >/dev/null 2>&1; then codex; fi; exec zsh -l'
tmux split-window -h -t "$SESSION:$DAEMON_WINDOW.0" -p 50 -c "$WORKDIR" /bin/zsh -l
tmux split-window -v -t "$SESSION:$DAEMON_WINDOW.0" -p 50 -c "$WORKDIR" /bin/zsh -l

# Pane 标题（显示在边框顶部）
# split -h 产生右侧 pane (1), split -v 产生左下 pane (2)
tmux select-pane -t "$SESSION:$DAEMON_WINDOW.0" -T "claude-keepalive"
tmux select-pane -t "$SESSION:$DAEMON_WINDOW.1" -T "work"
tmux select-pane -t "$SESSION:$DAEMON_WINDOW.2" -T "dsliam"

tmux select-pane -t "$SESSION:$DAEMON_WINDOW.1"
tmux select-window -t "$SESSION:$DAEMON_WINDOW"
exec tmux attach -t "$SESSION"
