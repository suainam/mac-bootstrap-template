#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../../" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

echo "=== Cleaning merged branches in parent repo ==="
cd "$ROOT"

merged_local=$(git branch --merged main | grep -v '^\*' | grep -v 'main' || true)
if [ -z "$merged_local" ]; then
  echo -e "${GREEN}No merged local branches to delete.${NC}"
else
  echo "$merged_local" | while read -r branch; do
    branch=$(echo "$branch" | xargs)
    echo -e "${YELLOW}Deleting local branch: $branch${NC}"
    git branch -d "$branch"
  done
fi

merged_remote=$(git branch -r --merged main | grep -v 'origin/main' | grep -v 'HEAD' || true)
if [ -z "$merged_remote" ]; then
  echo -e "${GREEN}No merged remote branches to delete.${NC}"
else
  echo "$merged_remote" | while read -r ref; do
    branch=$(echo "$ref" | sed 's|origin/||' | xargs)
    echo -e "${YELLOW}Deleting remote branch: $branch${NC}"
    git push origin --delete "$branch"
  done
fi

git remote prune origin 2>/dev/null || true

echo ""
echo "=== Cleaning merged branches in template repo ==="
cd "$ROOT/template"

merged_local=$(git branch --merged main | grep -v '^\*' | grep -v 'main' || true)
if [ -z "$merged_local" ]; then
  echo -e "${GREEN}No merged local branches to delete in template.${NC}"
else
  echo "$merged_local" | while read -r branch; do
    branch=$(echo "$branch" | xargs)
    echo -e "${YELLOW}Deleting local branch: $branch${NC}"
    git branch -d "$branch"
  done
fi

merged_remote=$(git branch -r --merged main | grep -v 'origin/main' | grep -v 'HEAD' || true)
if [ -z "$merged_remote" ]; then
  echo -e "${GREEN}No merged remote branches to delete in template.${NC}"
else
  echo "$merged_remote" | while read -r ref; do
    branch=$(echo "$ref" | sed 's|origin/||' | xargs)
    echo -e "${YELLOW}Deleting remote branch: $branch${NC}"
    git push origin --delete "$branch"
  done
fi

git remote prune origin 2>/dev/null || true

echo ""
echo -e "${GREEN}Branch cleanup complete.${NC}"
