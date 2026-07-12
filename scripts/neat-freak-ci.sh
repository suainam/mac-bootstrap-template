#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_REF="${NEAT_FREAK_BASE_REF:-HEAD~1}"

cd "$REPO_ROOT"

if ! git rev-parse --verify "${BASE_REF}^{commit}" >/dev/null 2>&1; then
  BASE_REF="$(git rev-parse HEAD^ 2>/dev/null || true)"
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

exec "$SCRIPT_DIR/neat-freak-gate.sh" check "${changed_paths[@]}"
