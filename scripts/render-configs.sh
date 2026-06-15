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
  local rel="$1"  # e.g. proxy/clash/Merge.yaml
  # Strip category prefix for private overlay lookup (proxy/clash/ -> clash/)
  local stripped="${rel#*/}"
  if [ "$stripped" = "$rel" ]; then stripped="$rel"; fi

  # Priority 1: external private overlay (private repo parent can pass this)
  if [ -n "$EXTERNAL_PRIVATE_DIR" ] && [ -f "$EXTERNAL_PRIVATE_DIR/$stripped" ]; then
    printf '%s\n' "$EXTERNAL_PRIVATE_DIR/$stripped"
    return 0
  fi
  # Priority 2: private parent layout: private-repo/template + private-repo/private
  if [ -f "$PARENT_DIR/private/$stripped" ]; then
    printf '%s\n' "$PARENT_DIR/private/$stripped"
    return 0
  fi
  # Priority 3: local private overlay
  if [ -f "$DIR/private/$stripped" ]; then
    printf '%s\n' "$DIR/private/$stripped"
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
    # Check if existing file has unresolved placeholders
    if grep -q '{{[A-Z_]' "$target" 2>/dev/null; then
      echo "  WARN: $rel has {{ placeholders — create private/${rel#*/} with real values"
      echo "       cp $source private/${rel#*/} \&\& vim private/${rel#*/}"
    else
      echo "  $rel: already present"
    fi
    return 0
  fi

  # Check if source contains unresolved {{ placeholders
  if grep -q '{{[A-Z_]' "$source" 2>/dev/null; then
    local stripped="${rel#*/}"
    local private_path=""
    for dir in "$EXTERNAL_PRIVATE_DIR" "$PARENT_DIR/private" "$DIR/private"; do
      if [ -n "$dir" ] && [ -f "$dir/$stripped" ]; then
        private_path="$dir/$stripped"
        break
      fi
    done
    if [ -z "$private_path" ]; then
      echo "  WARN: $rel still has {{ placeholders — create private/$stripped with real values"
      echo "       cp $source private/$stripped && vim private/$stripped"
      return 0
    fi
  fi

  run mkdir -p "$(dirname "$target")"
  run cp "$source" "$target"
  echo "  $rel <- $(label_path "$source")"
}

echo "=== Rendered configs ==="
render_config "proxy/clash/Merge.yaml"
render_config "infra/python/odps_config.py"

# ── LaunchAgent plists ──────────────────────────────────────
echo "=== LaunchAgent plists ==="
run mkdir -p "$HOME/Library/LaunchAgents"
for plist in "$DIR/launchd/"*.plist; do
  [ -f "$plist" ] || continue
  name="$(basename "$plist")"
  dst="$HOME/Library/LaunchAgents/$name"
  # Idempotent: skip if source and dest are identical
  if [ -f "$dst" ] && cmp -s "$plist" "$dst"; then
    echo "  $name: unchanged"
    continue
  fi
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
