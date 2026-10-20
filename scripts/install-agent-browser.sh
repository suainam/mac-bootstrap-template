#!/usr/bin/env bash
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"; SOURCE="$(readlink "$SOURCE")"; [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"; done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
TEMPLATE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  cat <<EOF
Usage: install-agent-browser.sh [options]

Install agent-browser — Vercel Labs browser automation CLI for AI agents.

Verifies installation via brew and triggers first-run setup to download Chrome for Testing.

Options:
  -h, --help    Show this help

References:
  - GitHub: vercel-labs/agent-browser (44.2k★)
  - Installed via Homebrew
  - Chrome profile: uses real Chrome at /Applications/Google Chrome.app
EOF
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Verify brew installation
if ! command -v agent-browser &>/dev/null; then
  echo "  WARN: agent-browser not found; run: brew install agent-browser" >&2
  exit 1
fi

echo "  agent-browser: $(command -v agent-browser)"
echo "  version: $(agent-browser --version 2>&1 | head -1 || echo 'unknown')"

# Trigger daemon start and Chrome download if not present
if [ ! -d "$HOME/.agent-browser/browsers" ]; then
  echo "  First run: downloading Chrome for Testing..."
  agent-browser list sessions &>/dev/null || true
fi

# Verify Chrome installation
if [ -d "$HOME/.agent-browser/browsers" ]; then
  CHROME_COUNT=$(ls -1d "$HOME/.agent-browser/browsers"/chrome-* 2>/dev/null | wc -l | tr -d ' ')
  echo "  Chrome for Testing: $CHROME_COUNT version(s) installed"
else
  echo "  WARN: Chrome for Testing not downloaded yet" >&2
fi

# Check profile reuse capability
if [ -d "/Applications/Google Chrome.app" ]; then
  echo "  Real Chrome profile: available at /Applications/Google Chrome.app"
  echo "  Usage: agent-browser --profile Default --executable-path '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' ..."
else
  echo "  Real Chrome profile: /Applications/Google Chrome.app not found (will use isolated Chrome for Testing)"
fi

echo "  status: ready"
