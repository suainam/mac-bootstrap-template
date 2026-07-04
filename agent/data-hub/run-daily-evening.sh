#!/usr/bin/env bash
# run-daily-evening.sh — 晚间全链路：ingest → auto_review → materialize → summary
# 触发时机: 工作日 18:00（由 launchd 调用）

set -euo pipefail

ROOT="${1:-$HOME/work/config/mac-bootstrap}"
TARGET_DATE="${2:-$(date +%F)}"

cd "$ROOT"

PYTHON="template/.venv/bin/python"
DATA_HUB="template/agent/data-hub"

echo "[evening] Starting full pipeline for $TARGET_DATE"

# 1. Ingest logs (Claude Code chat history)
echo "[evening] Step 1/5: ingest_logs"
$PYTHON "$DATA_HUB/ingest_logs.py"

# 2. Ingest sources (Obsidian meeting notes, xmind, etc.)
echo "[evening] Step 2/5: ingest_sources"
$PYTHON "$DATA_HUB/ingest_sources.py"

# 3. Generate candidates
echo "[evening] Step 3/5: generate_candidates"
$PYTHON "$DATA_HUB/generate_candidates.py" "$TARGET_DATE"

# 4. Auto-review candidates (confidence-based)
echo "[evening] Step 4/5: auto_review"
$PYTHON "$DATA_HUB/auto_review.py" "$TARGET_DATE"

# 5. Materialize accepted candidates
echo "[evening] Step 5/5: materialize_candidates"
$PYTHON "$DATA_HUB/materialize_candidates.py" "$TARGET_DATE"

# 6. Daily summary (AI-generated)
echo "[evening] Step 6/6: daily_summary"
$PYTHON "$DATA_HUB/daily_summary.py" "$TARGET_DATE"

echo "[evening] ✅ Full pipeline complete for $TARGET_DATE"
