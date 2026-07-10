#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" "$ROOT/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py" run --workflow build_daily_summary --date "$@"
