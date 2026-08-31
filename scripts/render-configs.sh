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

sync_clash_verge_profile() {
  local rel="clash/work-mac.yaml"
  local source

  # resolve_config strips the first path segment (proxy/clash/ -> clash/),
  # but "clash/work-mac.yaml" would become "work-mac.yaml" which is wrong.
  # Check private paths directly with the full relative path.
  local stripped="$rel"

  # Priority 1: external private overlay
  if [ -n "$EXTERNAL_PRIVATE_DIR" ] && [ -f "$EXTERNAL_PRIVATE_DIR/$stripped" ]; then
    source="$EXTERNAL_PRIVATE_DIR/$stripped"
  # Priority 2: private parent layout
  elif [ -f "$PARENT_DIR/private/$stripped" ]; then
    source="$PARENT_DIR/private/$stripped"
  # Priority 3: local private overlay
  elif [ -f "$DIR/private/$stripped" ]; then
    source="$DIR/private/$stripped"
  else
    echo "  WARN: no Clash profile source found for $rel"
    return 0
  fi


  # Runtime directory
  local clash_dir="$HOME/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev"
  local profiles_dir="$clash_dir/profiles"

  if [ ! -d "$profiles_dir" ]; then
    echo "  Clash Verge Profile: skipped (runtime directory missing)"
    return 0
  fi

  local profiles_yaml="$clash_dir/profiles.yaml"
  local current_uid=""
  if [ -f "$profiles_yaml" ]; then
    current_uid=$(awk '/^current:/ {print $2; exit}' "$profiles_yaml" 2>/dev/null)
  fi

  # A remote compatible profile is complete and server-owned. Never overwrite
  # it with the legacy local work-mac snapshot; refresh it through Clash Verge.
  local current_type=""
  current_type=$(awk -v uid="$current_uid" '
    function indent(line, prefix) {
      prefix = line
      sub(/[^[:space:]].*$/, "", prefix)
      return length(prefix)
    }
    /^[[:space:]]*-[[:space:]]+uid:/ {
      candidate = $0
      sub(/^[[:space:]]*-[[:space:]]+uid:[[:space:]]*/, "", candidate)
      sub(/[[:space:]]+#.*$/, "", candidate)
      sub(/[[:space:]]*$/, "", candidate)
      gsub(/"/, "", candidate)
      item_indent = indent($0)
      if (!found && candidate == uid) {
        found = 1
        target_indent = item_indent
        next
      }
      if (found && item_indent <= target_indent) exit
    }
    found && /^[[:space:]]+type:[[:space:]]*/ {
      value = $0
      sub(/^[[:space:]]*type:[[:space:]]*/, "", value)
      sub(/[[:space:]]+#.*$/, "", value)
      sub(/[[:space:]]*$/, "", value)
      gsub(/"/, "", value)
      print value
      exit
    }
  ' "$profiles_yaml" 2>/dev/null || true)
  if [ "$current_type" != "local" ]; then
    echo "  Clash Verge Profile: skipped (active profile type is ${current_type:-unknown}; refresh the remote compatible subscription)"
    return 0
  fi

  local target="$profiles_dir/${current_uid}.yaml"

  if [ -z "$target" ] || [ ! -f "$target" ]; then
    echo "  Clash Verge Profile: skipped (active local profile not found: ${current_uid:-none})"
    return 0
  fi

  run cp "$source" "$target"
  # Bump updated timestamp to trigger Clash Verge reload
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "
import re, time, sys
p = sys.argv[1]
uid = sys.argv[2]
with open(p) as f:
    content = f.read()
now = str(int(time.time()))
lines = content.split('\n')
in_target = False
updated = False
for i, line in enumerate(lines):
    if 'uid: ' + uid in line:
        in_target = True
        continue
    if in_target and re.match(r'^  updated:\s', line):
        lines[i] = '  updated: ' + now
        updated = True
        break
if updated:
    with open(p, 'w') as f:
        f.write('\n'.join(lines))
" "$profiles_yaml" "$current_uid" 2>/dev/null || true
  fi
  echo "  Clash Verge Profile <- $(label_path "$source") (active: $current_uid)"

  # Restart Clash Verge to force mihomo reload
  local clash_pid
  clash_pid=$(pgrep -f 'Clash Verge.app/Contents/MacOS/clash-verge' 2>/dev/null || true)
  if [ -n "$clash_pid" ]; then
    kill "$clash_pid" 2>/dev/null || true
    sleep 2
    open -a "Clash Verge" 2>/dev/null || true
    echo "  Clash Verge restarted (pid was $clash_pid)"
  else
    echo "  Clash Verge not running; profile will load on next launch"
  fi
}

echo "=== Rendered configs ==="
echo "  clash/work-mac.yaml: sync to active Clash Verge profile"
render_config "infra/python/odps_config.py"
echo "=== Runtime sync ==="
sync_clash_verge_profile

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
