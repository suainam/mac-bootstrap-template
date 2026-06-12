#!/usr/bin/env bash
# NOTE: 本地 docker/colima 已停用 (2026-06-12)
# 容器全部跑在远程堡垒机 dsliam 上。本脚本保留供恢复参考。
# 9router 配置在 ~/.9router/，docker-compose.yml 在本目录，重建：
#   brew install docker colima && colima start && docker compose up -d
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

echo "=== Register DevPod SSH provider (dsliam) ==="
if command -v devpod >/dev/null 2>&1; then
  if ! devpod provider list 2>/dev/null | grep -q 'dsliam'; then
    devpod provider add ssh --name dsliam \
      --option HOST=dsliam-devpod \
      --option USER=16620000611
    echo "  DevPod provider 'dsliam' registered"
  else
    echo "  DevPod provider 'dsliam' already exists"
  fi
else
  echo "  devpod not installed — skipping (run: brew install devpod)"
fi
