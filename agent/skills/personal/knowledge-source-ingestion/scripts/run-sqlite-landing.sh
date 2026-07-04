#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$HOME/work/config/mac-bootstrap}"
TARGET_DATE="${2:-$(date +%F)}"

cd "$ROOT"

template/.venv/bin/python template/agent/data-hub/ingest_logs.py
template/.venv/bin/python template/agent/data-hub/ingest_sources.py
template/.venv/bin/python template/agent/data-hub/generate_candidates.py "$TARGET_DATE"

echo
echo "== chat tables =="
sqlite3 "$ROOT/private/agent/data/agent_history.db" \
  "SELECT COUNT(*) AS sessions FROM sessions;
   SELECT COUNT(*) AS messages FROM messages;"

echo
echo "== source tables =="
sqlite3 "$ROOT/private/agent/data/agent_history.db" \
  "SELECT source_type, COUNT(*) FROM source_documents GROUP BY source_type ORDER BY source_type;"

echo
echo "== candidate tables =="
sqlite3 "$ROOT/private/agent/data/agent_history.db" \
  "SELECT candidate_date, candidate_type, status, COUNT(*)
   FROM knowledge_candidates
   GROUP BY candidate_date, candidate_type, status
   ORDER BY candidate_date DESC, candidate_type, status;"
