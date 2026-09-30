#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/install-maintenance-agents.sh" install cache-cleanup

