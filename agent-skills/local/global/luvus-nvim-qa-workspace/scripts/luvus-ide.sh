#!/usr/bin/env bash
# luvus-ide.sh: Single-instance 3-pane Luvus terminal IDE bootstrap.
# Usage: luvus-ide.sh [project-dir] [--new-tab] [--watch]
#
# - Single-instance guard: detects existing IDE panes by semantic names
# - Labels semantic roles: agent / nvim / qa-runtime (via luvus pane name / agent send)
# - Launches Neovim with RPC socket and optional qa-watch.sh daemon
# - Luvus port of herdr-nvim-qa-workspace/scripts/herdr-ide.sh

set -euo pipefail

test "${LUVUS_ENV:-}" = 1 || { echo "❌ Run inside a Luvus session (LUVUS_ENV=1)" >&2; exit 1; }

PROJECT_DIR="${1:-$PWD}"
shift || true

NEW_TAB=false
WATCH=false

for arg in "$@"; do
  case "$arg" in
    --new-tab|-t) NEW_TAB=true ;;
    --watch|-w)   WATCH=true ;;
  esac
done

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_REALPATH="$(cd "$PROJECT_DIR" && pwd -P)"
PROJECT_NAME="$(basename "$TARGET_REALPATH")"
SOCK_PATH="/tmp/nvim-luvus-${PROJECT_NAME}.sock"

# ==============================================================================
# 单例检测：已有 agent/nvim/qa-runtime 命名窗格即视为运行中
# ==============================================================================
EXIST_PANES=$(python3 -c "
import subprocess, json
try:
    raw = subprocess.check_output(['luvus', 'pane', 'list'], text=True)
    panes = json.loads(raw).get('result', {}).get('panes', [])
    agents = json.loads(subprocess.check_output(['luvus', 'agent', 'list'], text=True)).get('result', {}).get('agents', [])
    agent_names = {a.get('pane'): a.get('name') for a in agents if a.get('name')}
    named = [agent_names.get(p.get('pane')) for p in panes if agent_names.get(p.get('pane')) in ['nvim', 'qa-runtime', 'agent']]
    if 'nvim' in named and ('qa-runtime' in named or len(panes) >= 3):
        print('found')
except Exception:
    pass
" 2>/dev/null || true)

if [ "$EXIST_PANES" = "found" ]; then
  echo "ℹ️  [单例检测通过] Luvus 终端 IDE 已在运行，无需重复启动！"
  luvus pane list
  exit 0
fi

# ==============================================================================
# 创建 3-pane 拓扑
# ==============================================================================
if [ "$NEW_TAB" = true ]; then
  echo "📑 正在为项目 '$PROJECT_NAME' 创建独立 Luvus 标签页..."
  luvus tab new
fi

AGENT_PANE="${LUVUS_PANE_ID:-1}"
luvus pane name agent --pane "$AGENT_PANE" >/dev/null 2>&1 || true

PANE_NVIM=$(luvus pane split "$AGENT_PANE" --no-focus | jq -r '.result.pane')
luvus pane name nvim --pane "$PANE_NVIM" >/dev/null 2>&1 || true

PANE_QA=$(luvus pane split "$PANE_NVIM" --down --no-focus | jq -r '.result.pane')
luvus pane name qa-runtime --pane "$PANE_QA" >/dev/null 2>&1 || true

# 启动 Neovim（项目隔离 RPC + 兼容 /tmp/nvim-luvus.sock）
luvus pane send "$PANE_NVIM" "rm -f '$SOCK_PATH' /tmp/nvim-luvus.sock && ln -sfn '$SOCK_PATH' /tmp/nvim-luvus.sock && nvim --listen '$SOCK_PATH' .
"

if [ "$WATCH" = true ]; then
  luvus pane send "$PANE_QA" "$SKILL_DIR/scripts/qa-watch.sh
"
else
  luvus pane send "$PANE_QA" "echo '=== [qa-runtime] Playwriter & Dev Runtime Ready ==='
"
fi

echo "✨ 终端 IDE 初始化就绪："
echo "   - agent       : $AGENT_PANE"
echo "   - nvim        : $PANE_NVIM"
echo "   - qa-runtime  : $PANE_QA"
echo "   - target path : $TARGET_REALPATH"
