#!/usr/bin/env bash
set -euo pipefail

if ! command -v yazi >/dev/null 2>&1; then
  echo "yazi not found in PATH."
  echo "Install it with: brew install yazi"
  echo
  exec /bin/zsh -l
fi

exec yazi "$@"
