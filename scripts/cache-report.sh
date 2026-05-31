#!/usr/bin/env bash
set -euo pipefail

HOME_DIR="${HOME:?}"

print_section() {
  local title="$1"
  shift

  echo "=== $title ==="
  "$@"
  echo
}

print_section "Top ~/.cache entries" \
  sh -c "du -sh \"$HOME_DIR\"/.cache/* 2>/dev/null | sort -h | tail -n 15"

print_section "Top ~/Library/Caches entries" \
  sh -c "du -sh \"$HOME_DIR\"/Library/Caches/* 2>/dev/null | sort -h | tail -n 15"

print_section "Top tool-state directories" \
  sh -c "zsh -lc 'setopt NULL_GLOB; du -sh \"$HOME_DIR\"/.[!.]* \"$HOME_DIR\"/..?* 2>/dev/null | sort -h | tail -n 20'"
