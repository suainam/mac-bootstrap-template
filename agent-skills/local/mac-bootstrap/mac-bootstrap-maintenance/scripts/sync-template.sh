#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../../" && pwd)"
TEMPLATE="$ROOT/template"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

echo "=== Step 1: Pull latest template ==="
cd "$TEMPLATE"
git pull --ff-only origin main || {
  echo -e "${RED}FAIL: template pull failed (conflict?). Resolve manually.${NC}"
  exit 1
}
echo -e "${GREEN}Template updated to $(git rev-parse --short HEAD)${NC}"

echo ""
echo "=== Step 2: Stage submodule pointer in parent ==="
cd "$ROOT"
git add template
if git diff --cached --quiet; then
  echo -e "${GREEN}Submodule pointer already up to date. Nothing to commit.${NC}"
  exit 0
fi

echo ""
echo "=== Step 3: Verify before commit ==="
make check || {
  echo -e "${RED}FAIL: make check failed. Do not commit.${NC}"
  exit 1
}

echo ""
echo "=== Step 4: Commit and push ==="
git commit -m "Update template submodule to $(cd template && git rev-parse --short HEAD)"
git push origin main
echo -e "${GREEN}Done. Parent repo updated and pushed.${NC}"
