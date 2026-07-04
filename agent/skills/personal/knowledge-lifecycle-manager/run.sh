#!/usr/bin/env bash
# Knowledge Lifecycle Manager wrapper script
# Routes CLI args directly to manager.py

set -euo pipefail

REPO_ROOT="${HOME}/work/config/mac-bootstrap"
PYTHON="${REPO_ROOT}/template/.venv/bin/python"
MANAGER="${REPO_ROOT}/template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py"

exec "$PYTHON" "$MANAGER" "$@"
