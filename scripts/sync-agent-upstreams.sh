#!/usr/bin/env bash
set -euo pipefail

AGENT_HOME="${AGENT_HOME:-$HOME/.agent}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/sync-agent-upstreams.sh [--dry-run]

Clone or fast-forward agent upstream material libraries into ~/.agent, then
promote a small whitelist of useful skills.

Skill promotion lists live in agent/skills-promote.txt (canonical source).
Edit that file, not this script.

Environment:
  AGENT_HOME  Override target agent home. Defaults to ~/.agent.
EOF
}

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

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRY-RUN:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

sync_repo() {
  local name="$1"
  local repo="$2"
  local dest="$3"

  if [ -d "$dest/.git" ]; then
    echo "=== Update $name ==="
    run git -C "$dest" pull --ff-only
  else
    echo "=== Clone $name ==="
    run git clone "$repo" "$dest"
  fi
}

promote_skill_dir() {
  local src="$1"
  local dest="$2"

  if [ ! -d "$src" ]; then
    echo "  Skip missing skill: $src" >&2
    return 0
  fi

  run mkdir -p "$(dirname "$dest")"
  if [ "$DRY_RUN" -eq 1 ]; then
    run rsync -a --delete "$src/" "$dest/"
  else
    rsync -a --delete "$src/" "$dest/"
  fi
  echo "  Promoted $(basename "$dest")"
}

find_skill_dir() {
  local root="$1"
  local name="$2"

  for candidate in \
    "$root/skills/$name" \
    "$root/.agents/skills/$name" \
    "$root/.claude/skills/$name" \
    "$root/$name"
  do
    if [ -f "$candidate/SKILL.md" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  find "$root" -maxdepth 6 -path "*/$name/SKILL.md" -print -quit 2>/dev/null | sed 's#/SKILL.md$##'
}

# Read skill promotion lists from canonical file
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_FILE="$REPO_DIR/agent/skills-promote.txt"

read_section() {
  local section="$1"
  awk -v sec="$section" '
    $0 ~ "^# ── " sec " ──" {found=1; next}
    found && /^# ── / {exit}
    found && /^[a-zA-Z0-9_.\/-]+$/ {print}
  ' "$SKILLS_FILE"
}

ECC_SKILLS=()
POCOCK_SKILLS=()
KHAZIX_SKILLS=()
PERSONAL_SKILLS=()

while IFS= read -r skill; do
  ECC_SKILLS+=("$skill")
done < <(read_section "everything-claude-code")

while IFS= read -r skill; do
  POCOCK_SKILLS+=("$skill")
done < <(read_section "mattpocock-skills")

while IFS= read -r skill; do
  KHAZIX_SKILLS+=("$skill")
done < <(read_section "khazix-skills")

while IFS= read -r skill; do
  PERSONAL_SKILLS+=("$skill")
done < <(read_section "personal")

run mkdir -p "$AGENT_HOME/upstream" "$AGENT_HOME/skills/upstream" "$AGENT_HOME/skills/personal"

sync_repo \
  "everything-claude-code" \
  "https://github.com/affaan-m/everything-claude-code.git" \
  "$AGENT_HOME/upstream/everything-claude-code"

sync_repo \
  "mattpocock-skills" \
  "https://github.com/mattpocock/skills.git" \
  "$AGENT_HOME/upstream/mattpocock-skills"

sync_repo \
  "khazix-skills" \
  "https://github.com/KKKKhazix/khazix-skills.git" \
  "$AGENT_HOME/upstream/khazix-skills"

echo "=== Promote ECC Python/data skills ==="
for skill in "${ECC_SKILLS[@]}"; do
  src="$(find_skill_dir "$AGENT_HOME/upstream/everything-claude-code" "$skill" || true)"
  if [ -z "$src" ]; then
    echo "  Skip missing ECC skill: $skill" >&2
    continue
  fi
  promote_skill_dir \
    "$src" \
    "$AGENT_HOME/skills/upstream/ecc/$skill"
done

echo "=== Promote Matt Pocock skills ==="
for skill in "${POCOCK_SKILLS[@]}"; do
  promote_skill_dir \
    "$AGENT_HOME/upstream/mattpocock-skills/$skill" \
    "$AGENT_HOME/skills/upstream/mattpocock/$(basename "$skill")"
done

echo "=== Promote Khazix skills ==="
for skill in "${KHAZIX_SKILLS[@]}"; do
  src="$(find_skill_dir "$AGENT_HOME/upstream/khazix-skills" "$skill" || true)"
  if [ -z "$src" ]; then
    echo "  Skip missing Khazix skill: $skill" >&2
    continue
  fi
  promote_skill_dir \
    "$src" \
    "$AGENT_HOME/skills/upstream/khazix/$skill"
done

echo "=== Link personal data skills ==="
for skill in "${PERSONAL_SKILLS[@]}"; do
  src="$REPO_DIR/agent/skills/personal/$skill"
  dest="$AGENT_HOME/skills/personal/$skill"
  run mkdir -p "$(dirname "$dest")"
  run ln -sfn "$src" "$dest"
  echo "  $dest -> $src"
done

echo "=== Done ==="
echo "Agent home: $AGENT_HOME"
