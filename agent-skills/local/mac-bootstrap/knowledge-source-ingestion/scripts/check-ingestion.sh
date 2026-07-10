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
DB="$REPO_ROOT/private/agent/data/agent_history.db"

cd "$REPO_ROOT"

"$PYTHON_BIN" "$TEMPLATE_ROOT/data-hub/scripts/ingest_sources.py"
"$PYTHON_BIN" -m py_compile \
  "$TEMPLATE_ROOT/data-hub/scripts/ingest_sources.py" \
  "$TEMPLATE_ROOT/data-hub/scripts/generate_candidates.py" \
  "$TEMPLATE_ROOT/data-hub/scripts/materialize_candidates.py" \
  "$TEMPLATE_ROOT/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py"

sqlite3 "$DB" \
  "SELECT source_type, title, path FROM source_documents ORDER BY captured_at DESC;"

sqlite3 "$DB" \
  "SELECT item_type, title, substr(content,1,100) FROM extracted_items ORDER BY rowid DESC LIMIT 20;"
