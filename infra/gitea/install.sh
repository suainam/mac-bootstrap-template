#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE="${GITEA_HOST:-}"
DEFAULT_REMOTE_DIR="${GITEA_DIR:-/srv/gitea}"

find_private_overlay_root() {
  if [ -n "${MAC_BOOTSTRAP_PRIVATE_DIR:-}" ] && [ -d "$MAC_BOOTSTRAP_PRIVATE_DIR" ]; then
    printf "%s" "$MAC_BOOTSTRAP_PRIVATE_DIR"
    return 0
  fi
  if [ -d "$DIR/../../private" ]; then
    (cd "$DIR/../../private" && pwd)
    return 0
  fi
  if [ -d "$DIR/../private" ]; then
    (cd "$DIR/../private" && pwd)
    return 0
  fi
  return 1
}

load_private_gitea_env() {
  local private_root env_file
  private_root="$(find_private_overlay_root 2>/dev/null || true)"
  [ -n "$private_root" ] || return 0

  env_file="$private_root/infra/gitea/env.sh"
  if [ -f "$env_file" ]; then
    # shellcheck disable=SC1090
    . "$env_file"
  fi
}

load_private_gitea_env
REMOTE="${GITEA_HOST:-$REMOTE}"
DEFAULT_REMOTE_DIR="${GITEA_DIR:-$DEFAULT_REMOTE_DIR}"

discover_remote_dir() {
  if [ -n "${GITEA_DIR:-}" ]; then
    printf "%s" "$GITEA_DIR"
    return 0
  fi

  local detected
  detected="$(
    ssh "$REMOTE" \
      "docker inspect gitea --format '{{ index .Config.Labels \"com.docker.compose.project.working_dir\" }}' 2>/dev/null" \
      2>/dev/null || true
  )"

  if [ -n "$detected" ] && [ "$detected" != "<no value>" ]; then
    printf "%s" "$detected"
    return 0
  fi

  printf "%s" "$DEFAULT_REMOTE_DIR"
}

if [ -z "$REMOTE" ]; then
  echo "ERROR: GITEA_HOST is required. Put the real host in your private overlay or shell env." >&2
  exit 1
fi

REMOTE_DIR="$(discover_remote_dir)"

echo "=== Deploy Gitea scaffold to $REMOTE ==="
echo "  Target: $REMOTE:$REMOTE_DIR"
echo ""

if ! ssh -O check "$REMOTE" 2>/dev/null; then
  echo "⚠️  $REMOTE 的 ControlMaster socket 未建立"
  echo "   先运行: ssh $REMOTE"
  exit 1
fi

ssh "$REMOTE" "mkdir -p $REMOTE_DIR"
scp \
  "$DIR/docker-compose.yml" \
  "$DIR/.env.example" \
  "$DIR/README.md" \
  "$DIR/install.sh" \
  "$REMOTE:$REMOTE_DIR/"

echo "  ✅ docker-compose.yml, .env.example, README.md, install.sh -> $REMOTE:$REMOTE_DIR/"
echo ""
echo "Next:"
echo "  1. ssh $REMOTE"
echo "  2. cd $REMOTE_DIR"
echo "  3. cp .env.example .env && edit .env"
echo "  4. docker compose up -d"
