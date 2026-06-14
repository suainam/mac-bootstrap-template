#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE="${CODE_SERVER_HOST:-dsliam-mux}"
REMOTE_DIR="${CODE_SERVER_DIR:-/data01/suai/dev/code-server}"

echo "=== Deploy code-server config to $REMOTE ==="
echo "  Target: $REMOTE:$REMOTE_DIR"
echo ""

# 检查 ControlMaster socket 是否存活
if ! ssh -O check "$REMOTE" 2>/dev/null; then
  echo "⚠️  $REMOTE 的 ControlMaster socket 未建立"
  echo "   请先运行: ssh dsliam-mux"
  echo "   认证后 socket 会保持 8 小时，之后 scp/ssh 免密"
  exit 1
fi

# 推送文件
ssh "$REMOTE" "mkdir -p $REMOTE_DIR"
scp "$DIR/docker-compose.yml" "$DIR/Dockerfile" "$DIR/.env.example" "$REMOTE:$REMOTE_DIR/"
echo "  ✅ docker-compose.yml, Dockerfile, .env.example -> $REMOTE:$REMOTE_DIR/"

# 检查 .env 是否存在
if ! ssh "$REMOTE" "test -f $REMOTE_DIR/.env" 2>/dev/null; then
  echo ""
  echo "  ⚠️  远程 .env 不存在，请创建："
  echo "     ssh $REMOTE 'cp $REMOTE_DIR/.env.example $REMOTE_DIR/.env && vi $REMOTE_DIR/.env'"
fi

echo ""
echo "Done. 远程构建："
echo "  ssh $REMOTE 'cd $REMOTE_DIR && docker compose up -d --build'"
