#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-.venv/bin/python}"
LUAC="${LUAC:-luac}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

shell_files=()
while IFS= read -r -d '' path; do
  shell_files+=("$path")
done < <(git ls-files -z -- '*.sh')

for script in "${shell_files[@]}"; do
  bash -n "$script"
done

python_files=()
while IFS= read -r -d '' path; do
  python_files+=("$path")
done < <(git ls-files -z -- '*.py')

"$PYTHON" scripts/check-python-syntax.py "${python_files[@]}"

lua_files=()
while IFS= read -r -d '' path; do
  lua_files+=("$path")
done < <(git ls-files -z -- '*.lua')

if ((${#lua_files[@]})); then
  "$LUAC" -p "${lua_files[@]}"
fi
