#!/usr/bin/env bash
# git-worktree-add.sh: git worktree add wrapper with .worktreeinclude auto-carryover.
# Usage: git-worktree-add.sh [git worktree add arguments...]
#
# Automatically synchronizes files listed in .worktreeinclude (e.g. .env, secrets)
# from the main worktree to newly created worktrees.

set -euo pipefail

# 1. Execute the git worktree add command
git worktree add "$@"

# 2. Determine target worktree path
# Find the directory argument passed to git worktree add
TARGET_PATH=""
SKIP_NEXT=false

for arg in "$@"; do
  if [ "$SKIP_NEXT" = true ]; then
    SKIP_NEXT=false
    continue
  fi
  case "$arg" in
    -b|-B|--track|--lock|--reason)
      SKIP_NEXT=true
      ;;
    -d|--detach|--checkout|--no-checkout|--lock|--quiet|-q|-f|--force)
      ;;
    -*)
      ;;
    *)
      if [ -z "$TARGET_PATH" ]; then
        TARGET_PATH="$arg"
      fi
      ;;
  esac
done

if [ -z "$TARGET_PATH" ] || [ ! -d "$TARGET_PATH" ]; then
  exit 0
fi

# Resolve absolute paths
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
TARGET_ABS="$(cd "$TARGET_PATH" && pwd -P)"

# Prevent copying into self
if [ "$REPO_ROOT" = "$TARGET_ABS" ]; then
  exit 0
fi

INCLUDE_FILE="$REPO_ROOT/.worktreeinclude"

# 3. Synchronize files specified in .worktreeinclude
if [ -f "$INCLUDE_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    # Strip leading/trailing whitespace
    pattern=$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    
    # Skip comments and blank lines
    case "$pattern" in
      ""|\#*) continue ;;
    esac

    SRC="$REPO_ROOT/$pattern"
    DST="$TARGET_ABS/$pattern"

    if [ -e "$SRC" ]; then
      mkdir -p "$(dirname "$DST")"
      cp -a "$SRC" "$DST"
      echo "  [worktree-sync] carried: $pattern -> $TARGET_PATH"
    fi
  done < "$INCLUDE_FILE"
fi
