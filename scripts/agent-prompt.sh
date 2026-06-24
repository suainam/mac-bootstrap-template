#!/usr/bin/env bash
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  TARGET="$(readlink "$SOURCE")"
  case "$TARGET" in
    /*) SOURCE="$TARGET" ;;
    *) SOURCE="$DIR/$TARGET" ;;
  esac
done
BOOTSTRAP="$(cd -P "$(dirname "$SOURCE")/.." && pwd)"
PYTHON="${PYTHON:-$BOOTSTRAP/.venv/bin/python}"

if [ ! -x "$PYTHON" ]; then
  echo "Missing project Python: $PYTHON" >&2
  echo "Create or repair template/.venv before running agent-prompt." >&2
  exit 2
fi

exec "$PYTHON" "$BOOTSTRAP/scripts/agent-prompt-index.py" "$@"
