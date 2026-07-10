#!/usr/bin/env bash
# Knowledge Lifecycle Manager wrapper script
# Routes CLI args directly to manager.py

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
MANAGER="$SKILL_DIR/scripts/manager.py"

exec "$PYTHON" "$MANAGER" "$@"
