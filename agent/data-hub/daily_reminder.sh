#!/usr/bin/env bash
# daily_reminder.sh — 17:30 workday-only work-record reminder.

set -euo pipefail

ROOT="${1:-$HOME/work/config/mac-bootstrap}"
TODAY="${2:-$(date +%F)}"
PYTHON="${ROOT}/template/.venv/bin/python"

if ! "$PYTHON" -c "import sys; sys.path.insert(0, '${ROOT}/template/agent/data-hub'); import summary_calendar; raise SystemExit(0 if summary_calendar.should_run_scheduled_event('reminder', '${TODAY}') else 1)"; then
  echo "[daily_reminder] skip: non-workday ${TODAY}"
  exit 0
fi

osascript -e 'display notification "记得填写今天的工作记录，AI 总结将在 18:00 生成" with title "日报助手" sound name "Glass"' 2>/dev/null || true
echo "[daily_reminder] notified: ${TODAY}"
