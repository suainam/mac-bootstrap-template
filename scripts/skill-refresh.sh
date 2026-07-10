#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/skill-refresh.sh [--dry-run]

Compatibility wrapper for the registry-driven skill distributor.
The authoritative configuration is now:
  - agent/skills-sources.jsonc
  - agent/skill-targets.jsonc
EOF
}

DRY_RUN=0
while [ "$#" -gt 0 ]; do
  case "$1" in
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

python3 "$BOOTSTRAP/scripts/skill_supply_chain.py" check
if [ "$DRY_RUN" -eq 1 ]; then
  python3 "$BOOTSTRAP/scripts/skill_supply_chain.py" distribute --dry-run
else
  python3 "$BOOTSTRAP/scripts/skill_supply_chain.py" distribute
fi
