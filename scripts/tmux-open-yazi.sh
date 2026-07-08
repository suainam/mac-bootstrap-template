#!/usr/bin/env bash
set -euo pipefail

if ! command -v yazi >/dev/null 2>&1; then
  echo "yazi not found in PATH."
  echo "Install it with: brew install yazi"
  echo
  exec /bin/zsh -l
fi

# --pick: open yazi as a file chooser and send the selected file to the
# current nvim pane (or open it in nvim here if no nvim is focused).
if [[ "${1:-}" == "--pick" ]]; then
  tmp="$(mktemp -t yazi-chooser.XXXXXX)" || exit 1
  yazi --chooser-file="$tmp" "${@:2}"
  mapfile -t chosen < <(command cat -- "$tmp" 2>/dev/null || true)
  command rm -f -- "$tmp"
  [[ ${#chosen[@]} -eq 0 ]] && exit 0

  pane_cmd="$(tmux display-message -p '#{pane_current_command}' 2>/dev/null || true)"
  if [[ "$pane_cmd" == *nvim* || "$pane_cmd" == *vim* ]]; then
    for f in "${chosen[@]}"; do
      tmux send-keys -t "$TMUX_PANE" "Escape" ":e ${f:gs/ /\\ }" "Enter"
    done
  else
    exec nvim -- "${chosen[@]}"
  fi
  exit 0
fi

exec yazi "$@"
