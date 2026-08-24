#!/usr/bin/env bash
# cleanup-daemon-services.sh
# 审计并清理失效的 LaunchAgents 与脱离 Supervisor 的孤儿僵死进程

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

echo "🧹 [2/3] 审计脱离 Supervisor 监管的孤儿僵死进程..."
# 获取当前正常受 supervisor 监管的活动进程树 PID
ACTIVE_SUPERVISOR_PIDS="$(pgrep -f "scripts/devspace-supervisor.sh|scripts/devspace-tunnel-supervisor.sh" || true)"

ORPHAN_PIDS=""
while IFS= read -r pid; do
  [[ -z "$pid" ]] && continue
  ppid="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
  # 如果父进程为 1（init/launchd 孤儿）或不在活动 supervisor 列表中，则判定为僵死孤儿
  is_legit=0
  for spid in $ACTIVE_SUPERVISOR_PIDS; do
    if [[ "$ppid" == "$spid" ]]; then
      is_legit=1
      break
    fi
  done
  if [[ "$is_legit" -eq 0 ]]; then
    ORPHAN_PIDS="${ORPHAN_PIDS} ${pid}"
  fi
done < <(pgrep -f "scripts/devspace_local.py" || true)

ORPHAN_PIDS="$(echo "$ORPHAN_PIDS" | xargs)"
if [[ -n "$ORPHAN_PIDS" ]]; then
  echo "  - 正在回收孤儿僵死进程: $ORPHAN_PIDS"
  echo "$ORPHAN_PIDS" | xargs kill -9 2>/dev/null || true
else
  echo "  - 未发现脱离监管的孤儿进程（DevSpace 进程受 Supervisor 正常监管中）"
fi

echo "🧹 [3/3] 验证活动 LaunchAgent 服务状态..."
if launchctl list | grep -q "io.local.mac-bootstrap.devspace"; then
  echo "  - io.local.mac-bootstrap.devspace: 正常监管中"
fi

echo "✅ 常驻服务与守护进程审计清理完成！"
