#!/usr/bin/env bash

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
    run rm "$dest"
  elif [ -e "$dest" ]; then
    echo "  SKIP  $dest exists as real path (remove manually to symlink)"
    return 0
  fi

  run ln -s "$src_dir" "$dest"
}

wire_skill_dir() {
  local src_dir="$1"
  local skill_name="$2"

  src_dir="${src_dir%/}"
  [ -f "$src_dir/SKILL.md" ] || return 0

  if skill_has_target "$skill_name" "claude"; then
    link_skill_target "$src_dir" "$CLAUDE_SKILLS_DIR/${skill_name}"
  else
    run rm -rf "$CLAUDE_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "codex"; then
    link_skill_target "$src_dir" "$CODEX_SKILLS_DIR/${skill_name}"
  else
    run rm -rf "$CODEX_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "opencode"; then
    link_skill_target "$src_dir" "$OPENCODE_SKILLS_DIR/${skill_name}"
  else
    run rm -rf "$OPENCODE_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "cross-agent"; then
    link_skill_target "$src_dir" "$CROSS_AGENT_SKILLS_DIR/${skill_name}"
  else
    run rm -rf "$CROSS_AGENT_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "pi"; then
    run mkdir -p "$PI_SKILLS_DIR"
    link_skill_target "$src_dir" "$PI_SKILLS_DIR/${skill_name}"
  else
    run rm -rf "$PI_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "antigravity"; then
    link_skill_target "$src_dir" "$ANTIGRAVITY_SKILLS_DIR/${skill_name}"
  else
    run rm -rf "$ANTIGRAVITY_SKILLS_DIR/${skill_name}"
  fi

  if skill_has_target "$skill_name" "reasonix"; then
    run cp -L "$src_dir/SKILL.md" "$REASONIX_SKILLS_DIR/${skill_name}.md"
  else
    run rm -f "$REASONIX_SKILLS_DIR/${skill_name}.md"
  fi
}

wire_skill_tree() {
  local root="$1"
  [ -d "$root" ] || return 0
  for skill_dir in "$root"/*/; do
    [ -d "$skill_dir" ] || continue
    wire_skill_dir "$skill_dir" "$(basename "$skill_dir")"
  done
}

append_opencode_upstream_skills() {
  local target="$1"
  if [ -f "$target" ] && ! grep -q "Upstream Skills" "$target" 2>/dev/null; then
    if [ "${DRY_RUN:-0}" -eq 1 ]; then
      echo "DRY-RUN: append upstream skills section to $target"
    else
      cat >> "$target" <<'SKILLS'

## Upstream Skills

These skills are available as markdown files in `~/.agent/skills/upstream/`:
- ECC skills: ~/.agent/skills/upstream/ecc/*/
- Matt Pocock skills: ~/.agent/skills/upstream/mattpocock/*/
- Personal skills: ~/.agent/skills/personal/*/

Use the `Read` tool to load a skill file when needed, or ask the user which
skill to activate.
SKILLS
    fi
    echo "  OpenCode: upstream skills section added to AGENTS.md"
  fi
}
