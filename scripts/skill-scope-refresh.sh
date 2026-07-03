#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$REPO_DIR/agent/skills-manifest.json"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/skill-scope-refresh.sh [--dry-run]

Link first-party project-scoped skills from the canonical template skill tree
into repo-local `.agents/skills/` views.

The manifest only controls workspace scope:
- global  -> promoted by sync-agent-upstreams.sh into ~/.agent/skills/personal
- project -> linked by this script into the target repo `.agents/skills/`
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

manifest_lines() {
  python3 "$REPO_DIR/scripts/skill_scope_manifest.py" project-lines "$MANIFEST"
}

project_skill_dirs() {
  python3 - "$MANIFEST" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
for project in manifest.get("projects", {}).values():
    skills_dir = project.get("skills_dir")
    if skills_dir:
        print(skills_dir)
PY
}

expand_path() {
  local path="$1"
  path="${path/#\~/$HOME}"
  path="${path//\$\{HOME\}/$HOME}"
  path="${path//\$\{BOOTSTRAP\}/$REPO_DIR}"
  printf '%s\n' "$path"
}

link_skill() {
  local skill_name="$1"
  local source_rel="$2"
  local project_name="$3"
  local skills_dir_raw="$4"
  local source_dir skills_dir dest

  source_dir="$(expand_path "$REPO_DIR/$source_rel")"
  skills_dir="$(expand_path "$skills_dir_raw")"
  dest="$skills_dir/$skill_name"

  if [ ! -f "$source_dir/SKILL.md" ]; then
    echo "  Skip missing source for $skill_name: $source_dir" >&2
    return 0
  fi

  run mkdir -p "$skills_dir"
  if [ -L "$dest" ]; then
    run rm "$dest"
  elif [ -e "$dest" ]; then
    if [ -e "$dest.bak" ]; then
      echo "  SKIP  $dest exists as real path and $dest.bak already exists"
      return 0
    fi
    run mv "$dest" "$dest.bak"
    echo "  BACKUP $dest -> $dest.bak"
  fi
  run ln -s "$source_dir" "$dest"
  echo "  $project_name :: $skill_name -> $source_dir"
}

cleanup_stale_project_links() {
  local skills_dir_raw="$1"
  local skills_dir link target valid_names

  skills_dir="$(expand_path "$skills_dir_raw")"
  [ -d "$skills_dir" ] || return 0
  valid_names="$(awk -F '\t' -v dir="$skills_dir_raw" '$4 == dir { print $1 }' "$manifest_tmp")"

  for link in "$skills_dir"/*; do
    [ -L "$link" ] || continue
    target="$(readlink "$link" 2>/dev/null || true)"
    case "$target" in
      "$REPO_DIR"/agent/skills/personal/*)
        if ! printf '%s\n' "$valid_names" | grep -Fxq "$(basename "$link")"; then
          run rm "$link"
          echo "  CLEAN  stale project skill link removed: $link -> $target"
        fi
        ;;
    esac
  done
}

main() {
  if [ ! -f "$MANIFEST" ]; then
    echo "Missing skills manifest: $MANIFEST" >&2
    exit 2
  fi

  manifest_tmp="$(mktemp)"
  trap 'rm -f "$manifest_tmp"' EXIT
  manifest_lines > "$manifest_tmp"

  while IFS= read -r skills_dir; do
    [ -n "$skills_dir" ] || continue
    cleanup_stale_project_links "$skills_dir"
  done < <(project_skill_dirs)

  echo "=== Link project-scoped skills ==="
  while IFS=$'\t' read -r skill_name source_rel project_name skills_dir; do
    [ -n "$skill_name" ] || continue
    link_skill "$skill_name" "$source_rel" "$project_name" "$skills_dir"
  done < "$manifest_tmp"

  echo "=== Done ==="
}

main "$@"
