#!/usr/bin/env bash
# daily_reminder.sh — 17:30 workday-only work-record reminder.

set -euo pipefail

DATA_HUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_ROOT="$(cd "$DATA_HUB_DIR/.." && pwd)"
REPO_ROOT="$(cd "$TEMPLATE_ROOT/.." && pwd)"
PYTHON="${PYTHON:-$TEMPLATE_ROOT/.venv/bin/python}"

TODAY="${2:-$(date +%F)}"

if ! "$PYTHON" -c "import sys; sys.path.insert(0, '${DATA_HUB_DIR}'); import summary_calendar; raise SystemExit(0 if summary_calendar.should_run_scheduled_event('reminder', '${TODAY}') else 1)"; then
  echo "[daily_reminder] skip: non-workday ${TODAY}"
  exit 0
fi

osascript -e 'display notification "记得填写今天的工作记录，AI 总结将在 18:00 生成" with title "日报助手" sound name "Glass"' 2>/dev/null || true
echo "[daily_reminder] notified: ${TODAY}"
