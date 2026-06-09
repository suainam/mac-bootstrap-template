#!/usr/bin/env bash
set -euo pipefail

export ZELLIJ_SESSION="${ZELLIJ_SESSION:-ai-work}"
export ZELLIJ_DEFAULT_LAYOUT="${ZELLIJ_DEFAULT_LAYOUT:-ai-work}"

cd "$HOME"
exec zsh -l
