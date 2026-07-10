#!/usr/bin/env bash
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  SOURCE_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$SOURCE_DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
TEMPLATE_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
REPO_ROOT="$(cd "$TEMPLATE_ROOT/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$TEMPLATE_ROOT/.venv/bin/python}"
TARGET_DATE="${2:-$(date +%F)}"

cd "$REPO_ROOT"

"$PYTHON_BIN" "$TEMPLATE_ROOT/data-hub/scripts/ingest_logs.py"
"$PYTHON_BIN" "$TEMPLATE_ROOT/data-hub/scripts/ingest_sources.py"
"$PYTHON_BIN" "$TEMPLATE_ROOT/data-hub/scripts/generate_candidates.py" "$TARGET_DATE"

echo
echo "== chat tables =="
sqlite3 "$REPO_ROOT/private/agent/data/agent_history.db" \
  "SELECT COUNT(*) AS sessions FROM sessions;
   SELECT COUNT(*) AS messages FROM messages;"

echo
echo "== source tables =="
sqlite3 "$REPO_ROOT/private/agent/data/agent_history.db" \
  "SELECT source_type, COUNT(*) FROM source_documents GROUP BY source_type ORDER BY source_type;"

echo
echo "== candidate tables =="
sqlite3 "$REPO_ROOT/private/agent/data/agent_history.db" \
  "SELECT candidate_date, candidate_type, status, COUNT(*)
   FROM knowledge_candidates
   GROUP BY candidate_date, candidate_type, status
   ORDER BY candidate_date DESC, candidate_type, status;"
