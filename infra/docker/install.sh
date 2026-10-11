#!/usr/bin/env bash
# NOTE: 本地 docker/colima 已停用 (2026-06-12)
# 容器全部跑在远程堡垒机上。本脚本保留供恢复参考。
# 9router 配置在 ~/.9router/，docker-compose.yml 在本目录，重建：
#   brew install docker colima && colima start && docker compose up -d
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Link Colima config ==="
mkdir -p "$HOME/.colima/default"
if [ -f "$DIR/colima.yaml" ]; then
  ln -sf "$DIR/colima.yaml" "$HOME/.colima/default/colima.yaml"
  echo "  $HOME/.colima/default/colima.yaml -> docker/colima.yaml"
fi

echo "=== Local Docker runtime (Colima) ==="
echo "  Default bootstrap does not auto-start Colima or register its launch agent."
echo "  When local container runtime is needed, start explicitly via:"
echo "    COLIMA_PROXY_PORT=<port> make colima-start"

