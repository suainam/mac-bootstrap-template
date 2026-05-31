#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$DIR/private"
REPO_URL="${MAC_BOOTSTRAP_PRIVATE_REPO:-}"
BRANCH="${MAC_BOOTSTRAP_PRIVATE_BRANCH:-}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/sync-private-overlay.sh [options]

Options:
  --repo URL       Private git repo URL. Defaults to MAC_BOOTSTRAP_PRIVATE_REPO.
  --branch NAME    Branch to clone/pull. Defaults to MAC_BOOTSTRAP_PRIVATE_BRANCH.
  --dry-run        Print actions without running git.
  -h, --help       Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      REPO_URL="${2:?Missing value for --repo}"
      shift
      ;;
    --branch)
      BRANCH="${2:?Missing value for --branch}"
      shift
      ;;
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
    for arg in "$@"; do
      if [ -n "$REPO_URL" ]; then
        arg="${arg//$REPO_URL/<PRIVATE_REPO_URL>}"
      fi
      arg="${arg//$DIR/<repo>}"
      arg="${arg//$HOME/~}"
      printf ' %q' "$arg"
    done
    printf '\n'
  else
    "$@"
  fi
}

if [ -z "$REPO_URL" ]; then
  echo "No private repo configured. Set MAC_BOOTSTRAP_PRIVATE_REPO or pass --repo."
  exit 0
fi

if [ -d "$TARGET/.git" ]; then
  echo "Updating private overlay in private/ (URL suppressed)"
  if [ -n "$BRANCH" ]; then
    run git -C "$TARGET" fetch origin "$BRANCH"
    run git -C "$TARGET" checkout "$BRANCH"
    run git -C "$TARGET" pull --ff-only origin "$BRANCH"
  else
    run git -C "$TARGET" pull --ff-only
  fi
  exit 0
fi

if [ -e "$TARGET" ]; then
  echo "ERROR: private/ exists but is not a git checkout." >&2
  echo "Move it aside, or manage it manually without private-sync." >&2
  exit 1
fi

echo "Cloning private overlay into private/ (URL suppressed)"
if [ -n "$BRANCH" ]; then
  run git clone --branch "$BRANCH" "$REPO_URL" "$TARGET"
else
  run git clone "$REPO_URL" "$TARGET"
fi
