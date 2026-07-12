#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_REF="${NEAT_FREAK_BASE_REF-}"
ZERO_SHA="0000000000000000000000000000000000000000"

cd "$REPO_ROOT"

if [[ "$BASE_REF" == "$ZERO_SHA" ]]; then
  BASE_REF=""
elif [[ -n "$BASE_REF" ]] && ! git rev-parse --verify "${BASE_REF}^{commit}" >/dev/null 2>&1; then
  echo "ERROR: neat-freak base revision not found: $BASE_REF" >&2
  exit 2
fi

changed_paths=()
if [[ -n "$BASE_REF" ]]; then
  while IFS= read -r path; do
    changed_paths+=("$path")
  done < <(git diff --name-only "$BASE_REF...HEAD")
fi

while IFS= read -r path; do
  changed_paths+=("$path")
done < <(git diff --name-only)

while IFS= read -r path; do
  changed_paths+=("$path")
done < <(git diff --cached --name-only)

if ((${#changed_paths[@]})); then
  exec "$SCRIPT_DIR/neat-freak-gate.sh" check "${changed_paths[@]}"
else
  exec "$SCRIPT_DIR/neat-freak-gate.sh" check
fi
