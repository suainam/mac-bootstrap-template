#!/usr/bin/env bash
# run-daily-evening.sh — 18:00 summary automation adapter

set -euo pipefail

DATA_HUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_ROOT="$(cd "$DATA_HUB_DIR/.." && pwd)"
REPO_ROOT="$(cd "$TEMPLATE_ROOT/.." && pwd)"
PYTHON="${PYTHON:-$TEMPLATE_ROOT/.venv/bin/python}"

TARGET_DATE="${2:-$(date +%F)}"

cd "$REPO_ROOT"

SCHEDULE="$DATA_HUB_DIR/scripts/run_summary_schedule.py"

echo "[evening] Starting summary schedule for $TARGET_DATE"
"$PYTHON" "$SCHEDULE" --date "$TARGET_DATE"
echo "[evening] Summary schedule complete for $TARGET_DATE"
