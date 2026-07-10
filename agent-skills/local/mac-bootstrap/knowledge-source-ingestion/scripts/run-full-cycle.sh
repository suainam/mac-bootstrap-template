#!/usr/bin/env bash
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  SOURCE_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$SOURCE_DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE_ROOT="$(cd "$SKILL_DIR/../../../.." && pwd)"
REPO_ROOT="$(cd "$TEMPLATE_ROOT/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$TEMPLATE_ROOT/.venv/bin/python}"
TARGET_DATE="${2:-$(date +%F)}"
APPLY_REVIEWED="${APPLY_REVIEWED:-0}"

cd "$REPO_ROOT"

bash "$SKILL_DIR/scripts/run-sqlite-landing.sh" "$REPO_ROOT" "$TARGET_DATE"
"$PYTHON_BIN" "$TEMPLATE_ROOT/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py" run --workflow build_daily_summary --date "$TARGET_DATE"

if [[ "$APPLY_REVIEWED" == "1" ]]; then
  "$PYTHON_BIN" "$TEMPLATE_ROOT/data-hub/scripts/materialize_candidates.py" "$TARGET_DATE"
fi
