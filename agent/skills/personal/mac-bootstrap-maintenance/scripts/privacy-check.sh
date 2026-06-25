#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../../" && pwd)"
TEMPLATE="$ROOT/template"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

fail=0

echo "=== Parent privacy scan ==="
if git -C "$ROOT" grep -n -I -E \
  'AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|xox[baprs]-|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}' \
  -- . ':!template'; then
  echo -e "${RED}FAIL: possible secret in parent repo${NC}"
  fail=1
else
  echo -e "${GREEN}ok: parent repo clean${NC}"
fi

echo ""
echo "=== Template privacy scan ==="
if git -C "$TEMPLATE" grep -n -I -E \
  'AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|xox[baprs]-|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}'; then
  echo -e "${RED}FAIL: possible secret in template repo${NC}"
  fail=1
else
  echo -e "${GREEN}ok: template repo clean${NC}"
fi

echo ""
echo "=== Checking for private files in template tree ==="
if git -C "$TEMPLATE" ls-files \
  | grep -E '(^private/|(^|/)\.env$|(^|/)\.env\.|\.pem$|\.key$|\.p12$|\.pfx$|_key$)' \
  | grep -vE '(^|/)\.env\.example$'; then
  echo -e "${RED}FAIL: private files found in template git tree${NC}"
  fail=1
else
  echo -e "${GREEN}ok: no private files in template tree${NC}"
fi

echo ""
if [ "$fail" -eq 0 ]; then
  echo -e "${GREEN}All privacy checks passed.${NC}"
else
  echo -e "${RED}Privacy check FAILED. Do not push until resolved.${NC}"
  exit 1
fi
