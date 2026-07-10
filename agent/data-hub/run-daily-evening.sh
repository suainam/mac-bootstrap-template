#!/usr/bin/env bash
# run-daily-evening.sh — 18:00 summary automation adapter

set -euo pipefail

ROOT="${1:-$HOME/work/config/mac-bootstrap}"
TARGET_DATE="${2:-$(date +%F)}"

cd "$ROOT"

PYTHON="${ROOT}/template/.venv/bin/python"
SCHEDULE="${ROOT}/template/agent/data-hub/scripts/run_summary_schedule.py"

echo "[evening] Starting summary schedule for $TARGET_DATE"
"$PYTHON" "$SCHEDULE" --date "$TARGET_DATE"
echo "[evening] Summary schedule complete for $TARGET_DATE"
