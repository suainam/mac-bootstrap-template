#!/usr/bin/env bash
# Package Manager Detection — priority chain
# Usage: scripts/detect-package-manager.sh [--set-global <npm|pnpm|yarn|bun>]
# Returns: detected package manager name

set -euo pipefail

detect() {
  # 1. Environment variable
  if [ -n "${CLAUDE_PACKAGE_MANAGER:-}" ]; then
    echo "$CLAUDE_PACKAGE_MANAGER"; return
  fi

  # 2. Project config file
  if [ -f ".claude/package-manager.json" ]; then
    jq -r '.manager // empty' ".claude/package-manager.json" 2>/dev/null && return
  fi

  # 3. package.json packageManager field
  if [ -f "package.json" ]; then
    jq -r '.packageManager // empty' "package.json" 2>/dev/null | cut -d@ -f1 && return
  fi

  # 4. Lock file detection
  local pm=""
  [ -f "pnpm-lock.yaml" ] && pm="pnpm" || true
  [ -f "yarn.lock" ] && pm="yarn" || true
  [ -f "bun.lockb" ] && pm="bun" || true
  [ -f "package-lock.json" ] && pm="npm" || true
  [ -n "$pm" ] && { echo "$pm"; return; }

  # 5. Global user config
  if [ -f "$HOME/.claude/package-manager.json" ]; then
    jq -r '.manager // empty' "$HOME/.claude/package-manager.json" 2>/dev/null && return
  fi

  # 6. Fallback: first available
  for pm in pnpm yarn bun npm; do
    command -v "$pm" &>/dev/null && { echo "$pm"; return; }
  done

  echo "unknown"
}

case "${1:-}" in
  --set-global)
    pm="${2:-}"
    mkdir -p "$HOME/.claude"
    echo "{\"manager\": \"$pm\"}" > "$HOME/.claude/package-manager.json"
    echo "Set global package manager: $pm"
    ;;
  --set-project)
    pm="${2:-}"
    mkdir -p ".claude"
    echo "{\"manager\": \"$pm\"}" > ".claude/package-manager.json"
    echo "Set project package manager: $pm"
    ;;
  *)
    detect
    ;;
esac
