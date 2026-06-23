#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$BOOTSTRAP/agent/agent-manifest.json"
SKILL_DISTRIBUTION_FILE="$BOOTSTRAP/agent/skills-distribution.json"
HOME_DIR="${HOME}"

manifest_get() {
  local key="$1"
  python3 - "$MANIFEST" "$key" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
value = manifest
for part in sys.argv[2].split("."):
    value = value[part]
if isinstance(value, (dict, list)):
    print(json.dumps(value))
else:
    print(value)
PY
}

expand_path() {
  local path="$1"
  path="${path/#\~/$HOME_DIR}"
  path="${path//\$\{HOME\}/$HOME_DIR}"
  path="${path//\$\{BOOTSTRAP\}/$BOOTSTRAP}"
  printf '%s\n' "$path"
}

json_get_path() {
  local query="$1"
  expand_path "$(manifest_get "$query")"
}

CLAUDE_SKILLS_DIR="$(json_get_path agents.claude.paths.skills)"
CODEX_SKILLS_DIR="$(json_get_path agents.codex.paths.skills)"
OPENCODE_SKILLS_DIR="$(json_get_path agents.opencode.paths.skills)"
PI_SKILLS_DIR="$(json_get_path agents.pi.paths.skills)"
REASONIX_SKILLS_DIR="$(json_get_path agents.reasonix.paths.skills)"
ANTIGRAVITY_SKILLS_DIR="$(json_get_path agents.antigravity.paths.skills)"
CROSS_AGENT_SKILLS_DIR="$(json_get_path shared.cross_agent_skills_dir)"
AGENT_SKILLS_ROOT="$(json_get_path shared.upstream_skills_root)"

skill_targets() {
  local skill_name="$1"
  python3 - "$SKILL_DISTRIBUTION_FILE" "$skill_name" <<'PY'
import json
import sys

path, skill = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

skills = data.get("skills", {})
defaults = data.get("defaults", {})
apps = skills.get(skill, {}).get("apps", defaults.get("apps", []))
for app in apps:
    print(app)
PY
}

skill_has_target() {
  local skill_name="$1"
  local target="$2"
  local app
  while IFS= read -r app; do
    [ -n "$app" ] || continue
    if [ "$app" = "$target" ]; then
      return 0
    fi
  done < <(skill_targets "$skill_name")
  return 1
}

link_skill_target() {
  local src_dir="$1"
  local dest="$2"

  if [ -L "$dest" ]; then
    rm "$dest"
  elif [ -e "$dest" ]; then
    echo "  SKIP  $dest exists as real path (remove manually to symlink)"
    return 0
  fi

  ln -s "$src_dir" "$dest"
}

ensure_dirs() {
  mkdir -p \
    "$CLAUDE_SKILLS_DIR" \
    "$CODEX_SKILLS_DIR" \
    "$OPENCODE_SKILLS_DIR" \
    "$PI_SKILLS_DIR" \
    "$REASONIX_SKILLS_DIR" \
    "$ANTIGRAVITY_SKILLS_DIR" \
    "$CROSS_AGENT_SKILLS_DIR"
}

cleanup_legacy_claude_links() {
  local legacy legacy_path target
  for legacy in \
    cavecrew \
    caveman \
    caveman-commit \
    caveman-compress \
    caveman-help \
    caveman-review \
    caveman-stats
  do
    legacy_path="$CLAUDE_SKILLS_DIR/$legacy"
    if [ -L "$legacy_path" ]; then
      target="$(readlink "$legacy_path" 2>/dev/null || true)"
      case "$target" in
        "$HOME_DIR/.cc-switch/skills/"*)
          rm -f "$legacy_path"
          echo "Removed legacy Claude skill link: $legacy"
          ;;
      esac
    fi
  done
}

wire_skill_dir() {
  local src_dir="$1"
  local skill_name="$2"
  src_dir="${src_dir%/}"

  [ -f "$src_dir/SKILL.md" ] || return 0

  if skill_has_target "$skill_name" "claude"; then
    link_skill_target "$src_dir" "$CLAUDE_SKILLS_DIR/${skill_name}"
  else
    rm -rf "$CLAUDE_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "codex"; then
    link_skill_target "$src_dir" "$CODEX_SKILLS_DIR/${skill_name}"
  else
    rm -rf "$CODEX_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "opencode"; then
    link_skill_target "$src_dir" "$OPENCODE_SKILLS_DIR/${skill_name}"
  else
    rm -rf "$OPENCODE_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "cross-agent"; then
    link_skill_target "$src_dir" "$CROSS_AGENT_SKILLS_DIR/${skill_name}"
  else
    rm -rf "$CROSS_AGENT_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "pi"; then
    link_skill_target "$src_dir" "$PI_SKILLS_DIR/${skill_name}"
  else
    rm -rf "$PI_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "antigravity"; then
    link_skill_target "$src_dir" "$ANTIGRAVITY_SKILLS_DIR/${skill_name}"
  else
    rm -rf "$ANTIGRAVITY_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "reasonix"; then
    cp -L "$src_dir/SKILL.md" "$REASONIX_SKILLS_DIR/${skill_name}.md"
  else
    rm -f "$REASONIX_SKILLS_DIR/${skill_name}.md"
  fi
}

wire_tree() {
  local label="$1"
  local root="$2"
  local skill_dir name
  [ -d "$root" ] || return 0
  echo "$label"
  for skill_dir in "$root"/*/; do
    [ -d "$skill_dir" ] || continue
    name="$(basename "$skill_dir")"
    wire_skill_dir "$skill_dir" "$name"
  done
}

main() {
  if [ ! -d "$AGENT_SKILLS_ROOT/upstream" ]; then
    echo "Missing upstream skills under $AGENT_SKILLS_ROOT. Run 'make agent-sync' first." >&2
    exit 2
  fi

  ensure_dirs
  cleanup_legacy_claude_links

  wire_tree "ECC skills → agents" "$AGENT_SKILLS_ROOT/upstream/ecc"
  wire_tree "Matt Pocock skills → agents" "$AGENT_SKILLS_ROOT/upstream/mattpocock"
  wire_tree "Khazix skills → agents" "$AGENT_SKILLS_ROOT/upstream/khazix"
  wire_tree "Garden skills → agents" "$AGENT_SKILLS_ROOT/upstream/garden"
  wire_tree "Humanizer skills → agents" "$AGENT_SKILLS_ROOT/upstream/humanizer"
  wire_tree "Obsidian skills → agents" "$AGENT_SKILLS_ROOT/upstream/obsidian"
  wire_tree "Personal skills → agents" "$AGENT_SKILLS_ROOT/personal"

  echo "Skill refresh done."
}

main "$@"
