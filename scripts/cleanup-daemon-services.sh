#!/usr/bin/env bash
# cleanup-daemon-services.sh
# 审计并清理失效的 LaunchAgents 与堆积的僵死常驻进程

set -euo pipefail

UID_VAL="$(id -u)"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"

echo "🧹 [1/3] 审计并卸载已废弃/失效的 LaunchAgents..."
DEPRECATED_LABELS=(
  "io.local.mac-bootstrap.ssh-reverse-tunnel"
  "io.local.mac-bootstrap.zellij-host"
)

# 动态发现历史遗留的不同用户名前缀的失效 plist (例如 io.*.mac-bootstrap.*)
if [[ -d "$LAUNCH_AGENTS_DIR" ]]; then
  while IFS= read -r plist_file; do
    [[ -z "$plist_file" ]] && continue
    base_name="$(basename "$plist_file" .plist)"
    if [[ "$base_name" =~ ^io\..+\.mac-bootstrap\.(downloads-organizer|cache-cleanup)$ && "$base_name" != "io.local.mac-bootstrap."* ]]; then
      DEPRECATED_LABELS+=("$base_name")
    fi
  done < <(find "$LAUNCH_AGENTS_DIR" -name "io.*.mac-bootstrap.*.plist" -maxdepth 1 2>/dev/null || true)
fi

for label in "${DEPRECATED_LABELS[@]}"; do
  if launchctl list | grep -q "$label" 2>/dev/null; then
    echo "  - 正在卸载: $label"
    launchctl bootout "gui/${UID_VAL}/${label}" 2>/dev/null || true
  fi
  if [[ -f "${LAUNCH_AGENTS_DIR}/${label}.plist" ]]; then
    echo "  - 正在删除 plist: ${label}.plist"
    rm -f "${LAUNCH_AGENTS_DIR}/${label}.plist"
  fi
done

echo "🧹 [2/3] 回收孤儿与僵死常驻进程 (DevSpace/Supervisor)..."
ZOMBIE_PIDS=$(pgrep -f "scripts/devspace_local.py" || true)
if [[ -n "$ZOMBIE_PIDS" ]]; then
  echo "  - 正在回收僵死 devspace_local 进程: $ZOMBIE_PIDS"
  echo "$ZOMBIE_PIDS" | xargs kill -9 2>/dev/null || true
else
  echo "  - 未发现僵死 devspace_local 进程"
fi

echo "🧹 [3/3] 验证活动 LaunchAgent 服务状态..."
if launchctl list | grep -q "io.local.mac-bootstrap.devspace"; then
  echo "  - io.local.mac-bootstrap.devspace: 正常监管中"
fi

echo "✅ 常驻服务与守护进程审计清理完成！"
