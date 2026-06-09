#!/usr/bin/env bash
set -u

STRICT=0
if [ "${1:-}" = "--strict" ]; then
  STRICT=1
fi

missing=0

has_formula() {
  brew list --formula | grep -qx "$1"
}

has_cask() {
  brew list --cask | grep -qx "$1"
}

has_app() {
  [ -d "/Applications/$1" ] || [ -d "$HOME/Applications/$1" ]
}

has_npm() {
  npm list -g "$1" --depth=0 >/dev/null 2>&1
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

check_formula() {
  local name="$1"
  if has_formula "$name"; then
    echo "ok formula: $name"
  else
    echo "missing formula: $name"
    missing=1
  fi
}

check_cask() {
  local token="$1"
  local app="$2"

  if has_cask "$token"; then
    echo "ok cask: $token"
  elif has_app "$app"; then
    echo "ok manual app: $app (not managed by brew cask: $token)"
  else
    echo "missing cask/app: $token ($app)"
    missing=1
  fi
}

check_npm() {
  local name="$1"
  if has_npm "$name"; then
    echo "ok npm: $name"
  else
    echo "missing npm: $name"
    missing=1
  fi
}

check_antigravity_cli() {
  if has_command agy; then
    echo "ok cli: antigravity (agy)"
  elif has_command antigravity; then
    echo "ok cli: antigravity"
  else
    echo "missing cli: antigravity (expected 'agy' or 'antigravity')"
    missing=1
  fi
}

echo "=== Formulae ==="
while IFS= read -r line; do
  case "$line" in
    brew\ \"*\")
      name="${line#brew \"}"
      name="${name%\"}"
      check_formula "$name"
      ;;
  esac
done < Brewfile

echo "=== Standalone CLIs ==="
check_antigravity_cli

echo "=== Casks and apps ==="
while IFS= read -r line; do
  case "$line" in
    cask\ \"microsoft-edge\")
      check_cask "microsoft-edge" "Microsoft Edge.app"
      ;;
    cask\ \"visual-studio-code\")
      check_cask "visual-studio-code" "Visual Studio Code.app"
      ;;
    cask\ \"clash-verge-rev\")
      check_cask "clash-verge-rev" "Clash Verge.app"
      ;;
    cask\ \"uuremote\")
      check_cask "uuremote" "UU远程.app"
      ;;
    cask\ \"claude-code\")
      check_cask "claude-code" "Claude Code.app"
      ;;
    cask\ \"bitwarden\")
      check_cask "bitwarden" "Bitwarden.app"
      ;;
    cask\ \"codex\")
      check_cask "codex" "Codex.app"
      ;;
    cask\ \"codex-app\")
      check_cask "codex-app" "Codex.app"
      ;;
    cask\ \"miniforge\")
      check_cask "miniforge" "Miniforge-Navigator.app"
      ;;
    cask\ \"*\")
      token="${line#cask \"}"
      token="${token%\"}"
      if has_cask "$token"; then
        echo "ok cask: $token"
      else
        echo "missing cask: $token"
        missing=1
      fi
      ;;
  esac
done < Brewfile

echo "=== npm CLIs ==="
while IFS= read -r line; do
  case "$line" in
    npm\ \"*\")
      name="${line#npm \"}"
      name="${name%\"}"
      check_npm "$name"
      ;;
  esac
done < Brewfile

if [ "$missing" -eq 0 ]; then
  echo "Doctor passed."
  exit 0
fi

if [ "$STRICT" -eq 1 ]; then
  echo "Doctor failed."
  exit 1
fi

echo "Doctor found missing items."
exit 0
