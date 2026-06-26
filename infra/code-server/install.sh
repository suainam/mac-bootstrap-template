#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE="${CODE_SERVER_HOST:-}"
DEFAULT_REMOTE_DIR="${CODE_SERVER_DIR:-/srv/code-server}"

discover_remote_dir() {
  if [ -n "${CODE_SERVER_DIR:-}" ]; then
    printf "%s" "$CODE_SERVER_DIR"
    return 0
  fi

  local detected
  detected="$(
    ssh "$REMOTE" \
      "docker inspect code-server --format '{{ index .Config.Labels \"com.docker.compose.project.working_dir\" }}' 2>/dev/null" \
      2>/dev/null || true
  )"

  if [ -n "$detected" ] && [ "$detected" != "<no value>" ]; then
    printf "%s" "$detected"
    return 0
  fi

  printf "%s" "$DEFAULT_REMOTE_DIR"
}

if [ -z "$REMOTE" ]; then
  echo "ERROR: CODE_SERVER_HOST is required. Put the real host in your private overlay or shell env." >&2
  exit 1
fi

REMOTE_DIR="$(discover_remote_dir)"

echo "=== Deploy code-server config to $REMOTE ==="
echo "  Target: $REMOTE:$REMOTE_DIR"
echo ""

# 检查 ControlMaster socket 是否存活
if ! ssh -O check "$REMOTE" 2>/dev/null; then
  echo "⚠️  $REMOTE 的 ControlMaster socket 未建立"
  echo "   请先运行: ssh $REMOTE"
  echo "   认证后 socket 会保持 8 小时，之后 scp/ssh 免密"
  exit 1
fi

# 推送文件
ssh "$REMOTE" "mkdir -p $REMOTE_DIR"
scp \
  "$DIR/docker-compose.yml" \
  "$DIR/Dockerfile" \
  "$DIR/nginx.conf" \
  "$DIR/entrypoint-nginx.sh" \
  "$DIR/Caddyfile" \
  "$DIR/.env.example" \
  "$REMOTE:$REMOTE_DIR/"
echo "  ✅ docker-compose.yml, Dockerfile, nginx.conf, entrypoint-nginx.sh, Caddyfile, .env.example -> $REMOTE:$REMOTE_DIR/"

# 检查 .env 是否存在
if ! ssh "$REMOTE" "test -f $REMOTE_DIR/.env" 2>/dev/null; then
  echo ""
  echo "  ⚠️  远程 .env 不存在，请创建："
  echo "     ssh $REMOTE 'cp $REMOTE_DIR/.env.example $REMOTE_DIR/.env && vi $REMOTE_DIR/.env'"
fi

echo ""
echo "Done. 远程构建："
echo "  ssh $REMOTE 'cd $REMOTE_DIR && docker compose up -d --build'"
