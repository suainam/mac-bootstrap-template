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
tmux select-pane -t "$SESSION:$DAEMON_WINDOW.1"
tmux select-window -t "$SESSION:$DAEMON_WINDOW"
exec tmux attach -t "$SESSION"
