#!/usr/bin/env bash
# Knowledge Record wrapper script
# Routes CLI args directly to the dedicated writer

set -euo pipefail

REPO_ROOT="${HOME}/work/config/mac-bootstrap"
PYTHON="${REPO_ROOT}/template/.venv/bin/python"
WRITER="${REPO_ROOT}/template/agent-skills/local/mac-bootstrap/knowledge-record/scripts/record_knowledge.py"

exec "$PYTHON" "$WRITER" "$@"
