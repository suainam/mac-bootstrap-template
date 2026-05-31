#!/usr/bin/env bash
set -euo pipefail

MODE="safe"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --aggressive)
      MODE="aggressive"
      ;;
    -h|--help)
      cat <<'EOF'
Usage: clean-cache.sh [--aggressive]

Modes:
  default       Safe cleanup of rebuildable caches only.
  --aggressive  Also clear npm/pip caches via tool-native commands.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done

run_cleanup() {
  local label="$1"
  shift

  echo "=== $label ==="
  if "$@"; then
    return 0
  fi

  echo "  Warning: $label failed; continuing because cache cleanup is non-critical." >&2
}

echo "=== Safe cache cleanup ==="

if command -v uv >/dev/null 2>&1; then
  run_cleanup "uv cache prune" uv cache prune
fi

if command -v brew >/dev/null 2>&1; then
  run_cleanup "brew cleanup -s" brew cleanup -s
fi

if [ "$MODE" = "aggressive" ] && command -v npm >/dev/null 2>&1; then
  run_cleanup "npm cache clean --force" npm cache clean --force
fi

if [ "$MODE" = "aggressive" ] && command -v pip >/dev/null 2>&1; then
  run_cleanup "pip cache purge" pip cache purge
fi

echo "Skipped project virtualenvs, ~/work data, Codex runtime cache, and browser profiles."
