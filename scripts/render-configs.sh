#!/usr/bin/env bash
# Render config templates → real configs.
#
# Priority (first wins):
#   1. External private dir: $MAC_BOOTSTRAP_PRIVATE_DIR/<file>
#   2. Parent private dir:   ../private/<file> when this repo is a submodule
#   3. Local private dir:    $REPO_DIR/private/<file>
#   4. Real config:         $REPO_DIR/<file>
#   5. Template:            $REPO_DIR/<file>.template
#
# Usage:
#   ./scripts/render-configs.sh                  # render all templates
#   ./scripts/render-configs.sh --dry-run        # show what would happen
#
# This is called automatically by install.sh. Run manually after cloning
# a private overlay or editing private/* files.

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PARENT_DIR="$(cd "$DIR/.." && pwd)"
EXTERNAL_PRIVATE_DIR="${MAC_BOOTSTRAP_PRIVATE_DIR:-}"
DRY_RUN=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "Usage: render-configs.sh [--dry-run]"
      exit 0 ;;
    *) echo "Unknown: $1" >&2; exit 2 ;;
  esac
  shift
done

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  [DRY-RUN]'
    for arg in "$@"; do
      arg="${arg//$DIR/<repo>}"
      arg="${arg//$HOME/~}"
      printf ' %q' "$arg"
    done
    printf '\n'
  else
    "$@"
  fi
}

label_path() {
  local path="$1"
  if [ -n "$EXTERNAL_PRIVATE_DIR" ]; then
    path="${path#$EXTERNAL_PRIVATE_DIR/}"
    if [ "$path" != "$1" ]; then
      printf 'private:%s\n' "$path"
      return 0
    fi
  fi
  path="${path#$PARENT_DIR/private/}"
  if [ "$path" != "$1" ]; then
    printf '../private/%s\n' "$path"
    return 0
  fi
  printf '%s\n' "${path#$DIR/}"
}

resolve_config() {
  local rel="$1"  # e.g. clash/Merge.yaml
  # Priority 1: external private overlay (private repo parent can pass this)
  if [ -n "$EXTERNAL_PRIVATE_DIR" ] && [ -f "$EXTERNAL_PRIVATE_DIR/$rel" ]; then
    printf '%s\n' "$EXTERNAL_PRIVATE_DIR/$rel"
    return 0
  fi
  # Priority 2: private parent layout: private-repo/template + private-repo/private
  if [ -f "$PARENT_DIR/private/$rel" ]; then
    printf '%s\n' "$PARENT_DIR/private/$rel"
    return 0
  fi
  # Priority 3: local private overlay
  if [ -f "$DIR/private/$rel" ]; then
    printf '%s\n' "$DIR/private/$rel"
    return 0
  fi
  # Priority 4: real config
  if [ -f "$DIR/$rel" ]; then
    printf '%s\n' "$DIR/$rel"
    return 0
  fi
  # Priority 5: template
  if [ -f "$DIR/$rel.template" ]; then
    printf '%s\n' "$DIR/$rel.template"
    return 0
  fi
  return 1
}

render_config() {
  local rel="$1"
  local target="$DIR/$rel"
  local source

  if ! source="$(resolve_config "$rel")"; then
    echo "  WARN: no $rel, private/$rel, or $rel.template found"
    return 0
  fi

  if [ "$source" = "$target" ]; then
    echo "  $rel: already present"
    return 0
  fi

  run mkdir -p "$(dirname "$target")"
  run cp "$source" "$target"
  echo "  $rel <- $(label_path "$source")"
}

echo "=== Rendered configs ==="
render_config "clash/Merge.yaml"
render_config "python/odps_config.py"

# ── LaunchAgent plists ──────────────────────────────────────
echo "=== LaunchAgent plists ==="
run mkdir -p "$HOME/Library/LaunchAgents"
for plist in "$DIR/launchd/"*.plist; do
  [ -f "$plist" ] || continue
  name="$(basename "$plist")"
  dst="$HOME/Library/LaunchAgents/$name"
  run cp "$plist" "$dst"
  # Replace {{BOOTSTRAP}} with the canonical repo path
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  $name: would substitute {{BOOTSTRAP}}"
  elif grep -q '{{BOOTSTRAP}}' "$dst" 2>/dev/null; then
      sed -i '' "s|{{BOOTSTRAP}}|$DIR|g" "$dst"
    echo "  $name: substituted {{BOOTSTRAP}}"
  else
    echo "  $name: copied (no substitutions)"
  fi
done

echo "=== Done ==="
