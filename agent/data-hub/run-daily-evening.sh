#!/usr/bin/env bash
# run-daily-evening.sh — 晚间全链路 manager adapter
# 触发时机: 工作日 18:00（由 launchd 调用）

set -euo pipefail

ROOT="${1:-$HOME/work/config/mac-bootstrap}"
TARGET_DATE="${2:-$(date +%F)}"

cd "$ROOT"

PYTHON="template/.venv/bin/python"
MANAGER="template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py"

echo "[evening] Starting workflow=full_cycle for $TARGET_DATE"
"$PYTHON" "$MANAGER" run --workflow full_cycle --date "$TARGET_DATE"
echo "[evening] Full pipeline complete for $TARGET_DATE"
