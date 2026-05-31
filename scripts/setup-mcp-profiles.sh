#!/usr/bin/env bash
set -euo pipefail

# MCP Profile System — enable/disable MCPs per project via env var
# Usage: source scripts/setup-mcp-profiles.sh
#        export ECC_DISABLED_MCPS="caveman-shrink,some-other-mcp"
#        make agent-tools

DRY_RUN=0
case "${1:-}" in --dry-run) DRY_RUN=1 ;; esac

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRY-RUN:'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

# ─── MCP Profile: define which MCPs are enabled by default ───
# Set ECC_DISABLED_MCPS env var to comma-separated list of MCP names to skip.
# Example: export ECC_DISABLED_MCPS="caveman-shrink,memory"

BOOTSTRAP="$(cd "$(dirname "$0")/.." && pwd)"
ZSH_FILE="${ZDOTDIR:-$HOME}/.zshrc"

MCP_DISABLE_BLOCK='# MCP profiles: disable specific MCPs per project
# Set ECC_DISABLED_MCPS to a comma-separated list of MCP names to skip.
# Example: export ECC_DISABLED_MCPS="caveman-shrink,memory"
if [ -n "${ECC_DISABLED_MCPS:-}" ]; then
  export ECC_DISABLED_MCPS
fi'

# Add to .zshrc if not already present
if [ -f "$ZSH_FILE" ]; then
  if grep -q 'ECC_DISABLED_MCPS' "$ZSH_FILE" 2>/dev/null; then
    echo "  MCP profile already in $ZSH_FILE"
  else
    echo "" >> "$ZSH_FILE"
    echo "$MCP_DISABLE_BLOCK" >> "$ZSH_FILE"
    echo "  Added MCP profile block to $ZSH_FILE"
  fi
fi

echo "  MCP profiles configured. Use: export ECC_DISABLED_MCPS=\"caveman-shrink\""
