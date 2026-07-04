#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$HOME/work/config/mac-bootstrap}"
DB="$ROOT/private/agent/data/agent_history.db"

cd "$ROOT"

template/.venv/bin/python template/agent/data-hub/ingest_sources.py
template/.venv/bin/python -m py_compile \
  template/agent/data-hub/ingest_sources.py \
  template/agent/data-hub/generate_candidates.py \
  template/agent/data-hub/materialize_candidates.py \
  template/agent/data-hub/daily_summary.py

sqlite3 "$DB" \
  "SELECT source_type, title, path FROM source_documents ORDER BY captured_at DESC;"

sqlite3 "$DB" \
  "SELECT item_type, title, substr(content,1,100) FROM extracted_items ORDER BY rowid DESC LIMIT 20;"
