#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$SCRIPT_DIR/../.venv/bin/python}"

exec "$PYTHON" "$SCRIPT_DIR/agent_quality_gate.py" "$@"
