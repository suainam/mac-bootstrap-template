#!/usr/bin/env bash
set -euo pipefail

AGENT_HOME="${AGENT_HOME:-$HOME/.agent}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/sync-agent-prompts.sh [--dry-run]

Clone or fast-forward prompt-library upstreams into ~/.agent/upstream, then
build ~/.agent/prompts/index.json for agent and future MCP lookup.

Environment:
  AGENT_HOME  Override target agent home. Defaults to ~/.agent.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRY-RUN:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

sync_repo() {
  local name="$1"
  local repo="$2"
  local dest="$3"

  if [ -d "$dest/.git" ]; then
    echo "=== Update prompt source: $name ==="
    run git -C "$dest" pull --ff-only
  else
    echo "=== Clone prompt source: $name ==="
    run git clone "$repo" "$dest"
  fi
}

BOOTSTRAP="$(cd "$(dirname "$0")/.." && pwd)"
SOURCES_FILE="$BOOTSTRAP/agent/prompts/sources.json"
PYTHON="${PYTHON:-$BOOTSTRAP/.venv/bin/python}"

if [ ! -x "$PYTHON" ]; then
  echo "Missing project Python: $PYTHON" >&2
  echo "Create or repair template/.venv before running prompt sync." >&2
  exit 2
fi

run mkdir -p "$AGENT_HOME/upstream" "$AGENT_HOME/prompts"

while IFS=$'\t' read -r name repo upstream_dir; do
  [ -n "$name" ] || continue
  sync_repo "$name" "$repo" "$AGENT_HOME/upstream/$upstream_dir"
done < <(
  "$PYTHON" - "$SOURCES_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

for name, cfg in data["sources"].items():
    print(f"{name}\t{cfg['repo']}\t{cfg['upstream_dir']}")
PY
)

if [ "$DRY_RUN" -eq 1 ]; then
  run "$PYTHON" "$BOOTSTRAP/scripts/agent-prompt-index.py" build
else
  AGENT_HOME="$AGENT_HOME" "$PYTHON" "$BOOTSTRAP/scripts/agent-prompt-index.py" build
fi

echo "=== Done ==="
echo "Prompt index: $AGENT_HOME/prompts/index.json"
echo "Try: $BOOTSTRAP/scripts/agent-prompt.sh list summarize"
