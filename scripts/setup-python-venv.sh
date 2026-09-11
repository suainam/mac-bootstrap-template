#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "Missing uv. Install it (brew install uv) before provisioning template/.venv." >&2
  exit 2
fi

cd "$TEMPLATE_ROOT"
uv sync --locked --group dev
echo "  template/.venv ready (uv sync --locked --group dev)"
