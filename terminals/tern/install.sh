#!/usr/bin/env bash
# install.sh — distribute Tern's config from this repo into Tern's config dir.
#
# Tern rewrites settings.json atomically (write temp + rename), which replaces a
# symlink with a plain file. So config is copied, not linked, and every write is
# guarded by a recorded hash: local edits made in Tern's Settings UI are never
# clobbered silently.
#
# Usage:
#   ./install.sh [sync|capture|status] [--force]
#
#   sync     (default) repo -> Tern. Skips a file whose on-disk copy changed
#            since the last sync unless --force.
#   capture  Tern -> private overlay. Pulls edits made in the app back into
#            private/terminals/tern/. Never writes the public template.
#   status   Show per-file state; changes nothing.
#
# Environment:
#   TERN_CONFIG_DIR              Tern's config dir (default: the macOS path).
#   MAC_BOOTSTRAP_PRIVATE_DIR    Private overlay root.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_ROOT="$(cd "$DIR/../.." && pwd)"
PARENT_DIR="$(cd "$TEMPLATE_ROOT/.." && pwd)"
EXTERNAL_PRIVATE_DIR="${MAC_BOOTSTRAP_PRIVATE_DIR:-}"

MODE="sync"
FORCE=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    sync|capture|status) MODE="$1" ;;
    --force) FORCE=1 ;;
    -h|--help)
      sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2 ;;
  esac
  shift
done

TARGET_DIR="${TERN_CONFIG_DIR:-$HOME/Library/Application Support/Tern}"
STATE_FILE="$TARGET_DIR/.mac-bootstrap.sha256"

private_root() {
  if [ -n "$EXTERNAL_PRIVATE_DIR" ]; then
    printf '%s\n' "$EXTERNAL_PRIVATE_DIR/terminals/tern"
  elif [ -d "$PARENT_DIR/private/terminals/tern" ]; then
    printf '%s\n' "$PARENT_DIR/private/terminals/tern"
  elif [ -d "$TEMPLATE_ROOT/private/terminals/tern" ]; then
    printf '%s\n' "$TEMPLATE_ROOT/private/terminals/tern"
  elif [ -d "$PARENT_DIR/private" ]; then
    printf '%s\n' "$PARENT_DIR/private/terminals/tern"
  fi
}

PRIVATE_ROOT="$(private_root)"

sha() {
  shasum -a 256 "$1" | awk '{print $1}'
}

state_hash() {
  [ -f "$STATE_FILE" ] || return 0
  awk -v rel="$1" '$2 == rel {print $1; exit}' "$STATE_FILE"
}

record_hash() {
  local rel="$1" hash="$2" tmp
  tmp="$(mktemp)"
  if [ -f "$STATE_FILE" ]; then
    awk -v rel="$rel" '$2 != rel' "$STATE_FILE" >"$tmp"
  fi
  printf '%s  %s\n' "$hash" "$rel" >>"$tmp"
  LC_ALL=C sort -k2 "$tmp" >"$STATE_FILE"
  rm -f "$tmp"
}

# Only explicit configuration files belong in the distribution set.
managed_paths() {
  awk '!/^[[:space:]]*#/ && NF {print $1}' "$DIR/managed.txt"
}

source_for() {
  local rel="$1"
  if [ -n "$PRIVATE_ROOT" ] && [ -f "$PRIVATE_ROOT/$rel" ]; then
    printf '%s\n' "$PRIVATE_ROOT/$rel"
  elif [ -f "$DIR/$rel" ]; then
    printf '%s\n' "$DIR/$rel"
  fi
}

ensure_bin_shim() {
  local app="/Applications/Tern.app/Contents/MacOS/tern"
  local shim="$HOME/.local/bin/tern"
  [ -x "$app" ] || return 0
  if [ -e "$shim" ] && [ ! -L "$shim" ]; then
    echo "  keep $shim (not a symlink)"
    return 0
  fi
  mkdir -p "$HOME/.local/bin"
  ln -sf "$app" "$shim"
  echo "  $shim -> $app"
}

do_sync() {
  local rel source target current new baseline failed=0
  mkdir -p "$TARGET_DIR"
  echo "=== Tern config: repo -> $TARGET_DIR ==="
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    source="$(source_for "$rel")"
    if [ -z "$source" ]; then
      echo "  skip $rel (no source)"
      continue
    fi
    target="$TARGET_DIR/$rel"
    new="$(sha "$source")"
    current=""
    [ -f "$target" ] && current="$(sha "$target")"

    if [ "$current" = "$new" ]; then
      record_hash "$rel" "$new"
      echo "  ok $rel (unchanged)"
      continue
    fi

    baseline="$(state_hash "$rel")"
    if [ ! -e "$target" ]; then
      mkdir -p "$(dirname "$target")"
      cp "$source" "$target"
      record_hash "$rel" "$new"
      echo "  seeded $rel"
      continue
    fi

    if [ "$FORCE" -eq 1 ] || { [ -n "$baseline" ] && [ "$current" = "$baseline" ]; }; then
      cp "$target" "$target.bak.$(date +%Y%m%d_%H%M%S)"
      cp "$source" "$target"
      record_hash "$rel" "$new"
      echo "  wrote $rel <- ${source#"$TEMPLATE_ROOT"/}"
      continue
    fi

    if [ -z "$baseline" ]; then
      cp "$target" "$target.bak.$(date +%Y%m%d_%H%M%S)"
      cp "$source" "$target"
      record_hash "$rel" "$new"
      echo "  adopted $rel (backup kept next to it)"
      continue
    fi

    echo "  CONFLICT $rel: changed in Tern since the last sync" >&2
    echo "    keep the app's copy:  $0 capture" >&2
    echo "    overwrite with repo:  $0 sync --force" >&2
    failed=1
  done < <(managed_paths)

  ensure_bin_shim
  echo "Restart Tern, or Settings -> Reload settings, to apply."
  return "$failed"
}

do_capture() {
  local rel target source
  if [ -z "$PRIVATE_ROOT" ]; then
    echo "No private overlay found (looked for \$MAC_BOOTSTRAP_PRIVATE_DIR, ../private, private)." >&2
    echo "Create private/terminals/tern/ first; captured files are machine-specific and never go to the template." >&2
    exit 1
  fi
  echo "=== Tern config: $TARGET_DIR -> $PRIVATE_ROOT ==="
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    target="$TARGET_DIR/$rel"
    [ -f "$target" ] || continue
    source="$(source_for "$rel")"
    if [ -f "$PRIVATE_ROOT/$rel" ] && [ "$(sha "$PRIVATE_ROOT/$rel")" = "$(sha "$target")" ]; then
      echo "  ok $rel (unchanged)"
      continue
    fi
    mkdir -p "$(dirname "$PRIVATE_ROOT/$rel")"
    cp "$target" "$PRIVATE_ROOT/$rel"
    record_hash "$rel" "$(sha "$target")"
    echo "  captured $rel"
  done < <(managed_paths)
  echo "Review the diff in $PRIVATE_ROOT before committing."
}

do_status() {
  local rel source target failed=0
  echo "Tern config dir: $TARGET_DIR"
  echo "Private overlay: ${PRIVATE_ROOT:-none}"
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    source="$(source_for "$rel")"
    target="$TARGET_DIR/$rel"
    if [ -z "$source" ]; then
      echo "  no-source $rel"
    elif [ ! -f "$target" ]; then
      echo "  missing   $rel"
      failed=1
    elif [ "$(sha "$source")" = "$(sha "$target")" ]; then
      echo "  ok        $rel"
    elif [ "$(sha "$target")" = "$(state_hash "$rel")" ]; then
      echo "  stale     $rel (repo changed; run sync)"
      failed=1
    else
      echo "  local     $rel (changed in Tern; capture or sync --force)"
      failed=1
    fi
  done < <(managed_paths)
  return "$failed"
}

case "$MODE" in
  sync) do_sync ;;
  capture) do_capture ;;
  status) do_status ;;
esac
