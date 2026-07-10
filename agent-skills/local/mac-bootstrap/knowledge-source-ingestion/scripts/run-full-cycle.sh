#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$HOME/work/config/mac-bootstrap}"
TARGET_DATE="${2:-$(date +%F)}"
APPLY_REVIEWED="${APPLY_REVIEWED:-0}"

cd "$ROOT"

bash .agents/skills/knowledge-source-ingestion/scripts/run-sqlite-landing.sh "$ROOT" "$TARGET_DATE"
template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py run --workflow build_daily_summary --date "$TARGET_DATE"

if [[ "$APPLY_REVIEWED" == "1" ]]; then
  template/.venv/bin/python template/agent/data-hub/scripts/materialize_candidates.py "$TARGET_DATE"
fi
