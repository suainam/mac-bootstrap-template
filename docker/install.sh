#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Link Colima config ==="
mkdir -p "$HOME/.colima/default"
if [ -f "$DIR/colima.yaml" ]; then
  ln -sf "$DIR/colima.yaml" "$HOME/.colima/default/colima.yaml"
  echo "  $HOME/.colima/default/colima.yaml -> docker/colima.yaml"
fi

echo "=== Start Colima (first boot creates VM) ==="
if ! colima status >/dev/null 2>&1; then
  colima start
  echo "  Colima started"
else
  echo "  Colima already running"
fi

echo "=== Register Colima launch agent (auto-start on boot) ==="
PLIST="$HOME/Library/LaunchAgents/homebrew.mxcl.colima.plist"
if [ -f "$PLIST" ]; then
  launchctl bootout gui/$(id -u) "$PLIST" 2>/dev/null || true
  launchctl bootstrap gui/$(id -u) "$PLIST"
  echo "  Launch agent registered"
fi

echo "=== Verify Docker ==="
docker info --format '{{.ServerVersion}}' 2>/dev/null && echo "  Docker {{.ServerVersion}} ready" || echo "  Docker not ready yet — try 'colima start'"
