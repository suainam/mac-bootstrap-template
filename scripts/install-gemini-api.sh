#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${GEMINI_INSTALL_DIR:-$HOME/.local/bin}"
FORCE=0

usage() {
  cat <<EOF
Usage: install-gemini-api.sh [options]

Install the official Google Gemini API CLI (gemini-api) into ~/.local/bin.

Options:
  --force       Reinstall or upgrade even if gemini-api is already installed
  -h, --help    Show this help

Environment:
  GEMINI_INSTALL_DIR   Override install directory (default: ~/.local/bin)
  GEMINI_VERSION       Pin release tag (default: latest)
EOF
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

if [ "$FORCE" -eq 0 ] && { command -v gemini-api >/dev/null 2>&1 || [ -x "$INSTALL_DIR/gemini-api" ]; }; then
  gemini-api --version 2>/dev/null || echo "gemini-api already installed at $INSTALL_DIR/gemini-api"
  exit 0
fi

mkdir -p "$INSTALL_DIR"
curl -fsSL https://raw.githubusercontent.com/google-gemini/gemini-api-cli/main/scripts/install.sh | \
  GEMINI_INSTALL_DIR="$INSTALL_DIR" bash
