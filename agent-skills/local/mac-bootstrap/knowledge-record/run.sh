#!/usr/bin/env bash
# Knowledge Record wrapper script
# Routes CLI args directly to the dedicated writer

set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  SOURCE_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$SOURCE_DIR/$SOURCE"
done
SKILL_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
TEMPLATE_ROOT="$(cd "$SKILL_DIR/../../../.." && pwd)"
PYTHON="${PYTHON:-$TEMPLATE_ROOT/.venv/bin/python}"
WRITER="$SKILL_DIR/scripts/record_knowledge.py"

exec "$PYTHON" "$WRITER" "$@"
