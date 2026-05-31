#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC_REPO="${PUBLIC_REPO:-${MAC_BOOTSTRAP_PUBLIC_REPO:-}}"
PUBLIC_REMOTE="${PUBLIC_REMOTE:-${MAC_BOOTSTRAP_PUBLIC_REMOTE:-}}"
BRANCH="${PUBLIC_BRANCH:-${MAC_BOOTSTRAP_PUBLIC_BRANCH:-main}}"
MESSAGE="${PUBLIC_COMMIT_MESSAGE:-Update public template}"
KEEP_WORKTREE=0

usage() {
  cat <<'EOF'
Usage: scripts/publish-public-template.sh [options]

Exports the public template view, commits it in a temporary repo, and pushes it.
Use PUBLIC_REPO=owner/name for GitHub or PUBLIC_REMOTE=<git-url> for any remote.

Options:
  --repo OWNER/NAME   GitHub public repo. Defaults to PUBLIC_REPO.
  --remote URL        Git remote URL. Defaults to PUBLIC_REMOTE.
  --branch NAME       Target branch. Defaults to PUBLIC_BRANCH or main.
  --message TEXT      Commit message.
  --keep-worktree     Print and keep the temporary export directory.
  -h, --help          Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      PUBLIC_REPO="${2:?Missing value for --repo}"
      shift
      ;;
    --remote)
      PUBLIC_REMOTE="${2:?Missing value for --remote}"
      shift
      ;;
    --branch)
      BRANCH="${2:?Missing value for --branch}"
      shift
      ;;
    --message)
      MESSAGE="${2:?Missing value for --message}"
      shift
      ;;
    --keep-worktree)
      KEEP_WORKTREE=1
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

redact_remote() {
  local value="$1"
  value="${value//@*/@}"
  value="${value#https://}"
  value="${value#http://}"
  printf '%s\n' "$value"
}

cleanup() {
  if [ "${TMP_ROOT:-}" ] && [ "$KEEP_WORKTREE" -ne 1 ]; then
    rm -rf "$TMP_ROOT"
  fi
}
trap cleanup EXIT

if [ -z "$PUBLIC_REPO" ] && [ -z "$PUBLIC_REMOTE" ]; then
  echo "Set PUBLIC_REPO=owner/name or PUBLIC_REMOTE=<git-url>." >&2
  exit 2
fi

if [ -n "$PUBLIC_REPO" ] && [ -z "$PUBLIC_REMOTE" ]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "gh is required when using PUBLIC_REPO. Use PUBLIC_REMOTE to skip gh." >&2
    exit 1
  fi
  if gh repo view "$PUBLIC_REPO" >/dev/null 2>&1; then
    echo "GitHub repo exists: $PUBLIC_REPO"
  else
    echo "Creating public GitHub repo: $PUBLIC_REPO"
    gh repo create "$PUBLIC_REPO" --public --description "Public mac-bootstrap template"
  fi
  PUBLIC_REMOTE="git@github.com:${PUBLIC_REPO}.git"
fi

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/mac-bootstrap-public.XXXXXX")"
EXPORT_DIR="$TMP_ROOT/export"

"$DIR/scripts/export-public-template.sh" --dest "$EXPORT_DIR" --init-git

git -C "$EXPORT_DIR" config user.name >/dev/null 2>&1 || \
  git -C "$EXPORT_DIR" config user.name "mac-bootstrap-public"
git -C "$EXPORT_DIR" config user.email >/dev/null 2>&1 || \
  git -C "$EXPORT_DIR" config user.email "mac-bootstrap-public@example.com"

git -C "$EXPORT_DIR" commit -m "$MESSAGE" >/dev/null
git -C "$EXPORT_DIR" branch -M "$BRANCH"
git -C "$EXPORT_DIR" remote add origin "$PUBLIC_REMOTE"
git -C "$EXPORT_DIR" fetch origin "$BRANCH" >/dev/null 2>&1 || true
git -C "$EXPORT_DIR" push --force-with-lease origin "$BRANCH"

echo "Published public template to $(redact_remote "$PUBLIC_REMOTE") on $BRANCH"
if [ "$KEEP_WORKTREE" -eq 1 ]; then
  echo "Kept export worktree: $EXPORT_DIR"
fi
