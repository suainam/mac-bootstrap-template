#!/usr/bin/env bash
# herdr-ide.sh: Single-instance 3-pane Herdr terminal IDE bootstrap.
# Usage: herdr-ide.sh [project-dir] [--new-tab] [--watch]
#
# - Multi-criteria preflight check: detects existing IDE tab by label or (CWD + topology)
# - Prevents duplicate tab/pane explosion across repeated agent/human invocations
# - Labels semantic roles: agent / nvim / qa-runtime
# - Launches Neovim with RPC socket and optional qa-watch.sh daemon

set -euo pipefail

test "${HERDR_ENV:-}" = 1 || { echo "❌ Run inside a Herdr session" >&2; exit 1; }

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
WORKSPACE_ID="$HERDR_WORKSPACE_ID"
TARGET_REALPATH="$(cd "$PROJECT_DIR" && pwd -P)"
PROJECT_NAME="$(basename "$TARGET_REALPATH")"
TAB_LABEL="IDE-$PROJECT_NAME"

# ==============================================================================
# 多维度单例 / 幂等性检测 (Multi-Criteria Idempotency Detection)
# ==============================================================================
# 判断依据：
# 1. 显式 Label 命中：是否存在标签为 "IDE-$PROJECT_NAME" 的 Tab
# 2. 真实路径 + 角色拓扑命中：是否存在某个 Tab，其内部已包含目标目录的 nvim/qa-runtime 窗格
# ==============================================================================
DETECT_RESULT=$(TARGET_REALPATH="$TARGET_REALPATH" WORKSPACE_ID="$WORKSPACE_ID" TAB_LABEL="$TAB_LABEL" python3 -c "
import subprocess, json, os, sys

workspace_id = os.environ.get('WORKSPACE_ID', '')
target_dir = os.environ.get('TARGET_REALPATH', '')
expected_label = os.environ.get('TAB_LABEL', '')

try:
    tabs_raw = subprocess.check_output(['herdr', 'tab', 'list', '--workspace', workspace_id], text=True)
    tabs = json.loads(tabs_raw).get('result', {}).get('tabs', [])
    panes_raw = subprocess.check_output(['herdr', 'pane', 'list', '--workspace', workspace_id], text=True)
    panes = json.loads(panes_raw).get('result', {}).get('panes', [])
except Exception:
    sys.exit(0)
found_tab_id = ''
found_tab_label = ''
reason = ''

for t in tabs:
    tid = t.get('tab_id', '')
    tlabel = t.get('label') or ''
    tpanes = [p for p in panes if p.get('tab_id') == tid]
    
    # 判准 1: 标签直接精确匹配
    if tlabel == expected_label:
        found_tab_id = tid
        found_tab_label = tlabel
        reason = f'标签匹配: {tlabel}'
        break
    
    # 判准 2: 目标真实路径 + 语义角色拓扑匹配
    matching_panes = [
        p for p in tpanes 
        if os.path.realpath(p.get('cwd', '')) == target_dir and p.get('label') in ['nvim', 'qa-runtime', 'agent']
    ]
    if len(matching_panes) >= 2:
        found_tab_id = tid
        found_tab_label = tlabel or '未命名'
        reason = f'拓扑与路径命中: Tab \"{found_tab_label}\" 已在 {target_dir} 运行 {len(matching_panes)} 个 IDE 窗格'
        break

if found_tab_id:
    print(f'{found_tab_id}|{found_tab_label}|{reason}')
" 2>/dev/null || true)

if [ -n "$DETECT_RESULT" ]; then
  IFS='|' read -r EXIST_TID EXIST_LABEL EXIST_REASON <<< "$DETECT_RESULT"
  echo "ℹ️  [单例检测通过] 项目 '$PROJECT_NAME' 的终端 IDE 已在运行，无需重复启动！"
  echo "   - 命中依据: $EXIST_REASON"
  echo "   - 所在标签: $EXIST_LABEL ($EXIST_TID)"
  echo "   - 当前拓扑:"
  herdr pane list --workspace "$WORKSPACE_ID" | jq -r --arg tid "$EXIST_TID" '.result.panes[] | select(.tab_id == $tid) | "     • [\(.label // "unlabeled")] \(.pane_id) (CWD: \(.cwd))"'
  exit 0
fi

# ==============================================================================
# 创建新工作区 (创建独立 Tab 或使用当前 Pane)
# ==============================================================================
if [ "$NEW_TAB" = true ]; then
  echo "📑 正在为项目 '$PROJECT_NAME' 创建独立 Herdr 标签页 ($TAB_LABEL)..."
  TAB_JSON=$(herdr tab create --workspace "$WORKSPACE_ID" --label "$TAB_LABEL" --cwd "$TARGET_REALPATH" --no-focus)
  AGENT_PANE=$(echo "$TAB_JSON" | jq -r '.result.root_pane.pane_id')
else
  AGENT_PANE="$HERDR_PANE_ID"
fi

# 1. 命名主控 Agent 窗格
herdr pane rename "$AGENT_PANE" "agent"

# 2. 向右分屏创建 Neovim 窗格 (宽 50%)
PANE_NVIM=$(herdr pane split --pane "$AGENT_PANE" --direction right --cwd "$TARGET_REALPATH" --no-focus | jq -r '.result.pane.pane_id')
herdr pane rename "$PANE_NVIM" "nvim"

# 3. 向下分屏创建 QA 运行时窗格 (高 50%)
PANE_QA=$(herdr pane split --pane "$PANE_NVIM" --direction down --cwd "$TARGET_REALPATH" --no-focus | jq -r '.result.pane.pane_id')
herdr pane rename "$PANE_QA" "qa-runtime"

# 4. 启动对应进程与项目隔离 RPC 套接字
SOCK_PATH="/tmp/nvim-herdr-${PROJECT_NAME}.sock"
herdr pane run "$PANE_NVIM" "rm -f '$SOCK_PATH' /tmp/nvim-herdr.sock; ln -sfn '$SOCK_PATH' /tmp/nvim-herdr.sock; nvim --listen '$SOCK_PATH' ."
if [ "$WATCH" = true ]; then
  herdr pane run "$PANE_QA" "$SKILL_DIR/scripts/qa-watch.sh"
else
  herdr pane run "$PANE_QA" "echo '=== [qa-runtime] Playwriter & Dev Runtime Ready ==='"
fi

echo "✨ 终端 IDE 初始化就绪："
echo "   - agent       : $AGENT_PANE"
echo "   - nvim        : $PANE_NVIM"
echo "   - qa-runtime  : $PANE_QA"
echo "   - target path : $TARGET_REALPATH"
