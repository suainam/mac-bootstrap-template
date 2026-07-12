#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
shift || true

paths=("$@")
has_docs=0
has_operational=0

is_doc_path() {
  case "$1" in
    docs/archive/*|*/docs/archive/*)
      return 1
      ;;
    *.md|docs/*|*/docs/*|README.md|*/README.md|CLAUDE.md|AGENTS.md|CONTEXT.md|*/CONTEXT.md)
      return 0
      ;;
  esac
  return 1
}

is_operational_path() {
  case "$1" in
    *.py|*.sh|*.lua|*.json|*.jsonc|*.yaml|*.yml|*.toml|*.ini|*.plist|*.lock|requirements*.txt|Makefile|*/Makefile|Brewfile|*/Brewfile|Dockerfile|*/Dockerfile|.github/workflows/*|*/.github/workflows/*|template/scripts/*|template/agent/*)
      return 0
      ;;
  esac
  return 1
}

for path in "${paths[@]}"; do
  if is_doc_path "$path"; then
    has_docs=1
  fi
  if is_operational_path "$path"; then
    has_operational=1
  fi
done

case "$mode" in
  check)
    if [[ "$has_operational" -eq 1 && "$has_docs" -eq 0 ]]; then
      echo "ERROR: operational changes detected without current public documentation changes" >&2
      exit 1
    fi
    echo "OK: neat-freak check passed"
    ;;
  apply)
    if [[ "$has_operational" -eq 1 && "$has_docs" -eq 0 ]]; then
      echo "ERROR: neat-freak apply blocked push because docs are not aligned" >&2
      exit 1
    fi
    echo "OK: neat-freak apply passed"
    ;;
  *)
    echo "Usage: neat-freak-gate.sh check|apply" >&2
    exit 2
    ;;
esac
