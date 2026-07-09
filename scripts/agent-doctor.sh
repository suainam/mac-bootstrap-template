#!/usr/bin/env bash
set -euo pipefail

# Agent health & security check
# Runs AgentShield scan + configuration verification

DRY_RUN=0
FIX=0
BOOTSTRAP="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$BOOTSTRAP/agent/agent-manifest.json"

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
  path="${path/#\~/$HOME}"
  printf '%s\n' "$path"
}

json_get_path() {
  expand_path "$(manifest_get "$1")"
}

CLAUDE_RULES_12="$(json_get_path agents.claude.paths.rules_12)"
CLAUDE_RULES_COMMON="$(json_get_path agents.claude.paths.rules_common)"
CLAUDE_RULES_PYTHON="$(json_get_path agents.claude.paths.rules_python)"
CLAUDE_SETTINGS="$(json_get_path agents.claude.paths.settings)"
CLAUDE_MCP_JSON="$(json_get_path agents.claude.paths.mcp)"
CLAUDE_SKILLS_DIR="$(json_get_path agents.claude.paths.skills)"

CODEX_TOML="$(json_get_path agents.codex.paths.config)"
CODEX_AGENTS="$(json_get_path agents.codex.paths.instructions)"
CODEX_HOOKS="$(json_get_path agents.codex.paths.hooks)"
CODEX_SKILLS_DIR="$(json_get_path agents.codex.paths.skills)"

OPENCODE_CONFIG="$(json_get_path agents.opencode.paths.config)"
OPENCODE_AGENTS="$(json_get_path agents.opencode.paths.instructions)"
OPENCODE_PLUGINS_DIR="$(json_get_path agents.opencode.paths.plugins)"
OPENCODE_SKILLS_DIR="$(json_get_path agents.opencode.paths.skills)"

PI_SETTINGS="$(json_get_path agents.pi.paths.settings)"
PI_MCP_JSON="$(json_get_path agents.pi.paths.mcp)"
PI_MODELS_JSON="$(json_get_path agents.pi.paths.models_json)"
PI_AGENTS="$(json_get_path agents.pi.paths.instructions)"
PI_SKILLS_DIR="$(json_get_path agents.pi.paths.skills)"
PI_EXTENSIONS_DIR="$(json_get_path agents.pi.paths.extensions)"
PI_LOCAL_PROVIDER="$(json_get_path agents.pi.paths.local_provider_extension)"

REASONIX_CONFIG="$(json_get_path agents.reasonix.paths.config)"
REASONIX_SKILLS_DIR="$(json_get_path agents.reasonix.paths.skills)"

ANTIGRAVITY_SETTINGS="$(json_get_path agents.antigravity.paths.settings)"
ANTIGRAVITY_MCP_JSON="$(json_get_path agents.antigravity.paths.mcp)"
ANTIGRAVITY_SKILLS_DIR="$(json_get_path agents.antigravity.paths.skills)"
WORK_ROOT="${WORK_ROOT:-$HOME/work}"
WORK_AGENTS="$WORK_ROOT/AGENTS.md"
WORK_GEMINI="$WORK_ROOT/GEMINI.md"
WORK_REASONIX="$WORK_ROOT/REASONIX.md"
GLOBAL_GEMINI="$HOME/.gemini/GEMINI.md"

usage() {
  cat <<'EOF'
Usage: scripts/agent-doctor.sh [options]

Check agent configuration health and security.

Options:
  --fix        Auto-fix security issues (runs agentshield --fix)
  --dry-run    Print actions without running
  -h, --help   Show this help

EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --fix) FIX=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRY-RUN:'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

check_contains() {
  local name="$1" path="$2" needle="$3"
  if [ -f "$path" ] && grep -q "$needle" "$path" 2>/dev/null; then
    echo "  OK   $name"
  else
    echo "  MISS $name"
  fi
}

check_max_lines() {
  local name="$1" path="$2" max_lines="$3"
  if [ -f "$path" ]; then
    local count
    count=$(wc -l < "$path" | tr -d ' ')
    if [ "$count" -le "$max_lines" ]; then
      echo "  OK   $name ($count lines)"
    else
      echo "  WARN $name too long ($count lines > $max_lines)"
    fi
  else
    echo "  MISS $name"
  fi
}

check_first_line() {
  local name="$1" path="$2" expected="$3"
  if [ -f "$path" ]; then
    local first
    first="$(head -n 1 "$path" 2>/dev/null || true)"
    if [ "$first" = "$expected" ]; then
      echo "  OK   $name"
    else
      echo "  WARN $name expected '$expected' got '$first'"
    fi
  else
    echo "  MISS $name"
  fi
}

echo "=== Agent Security Scan ==="
if command -v npx &>/dev/null; then
  AGENTSHIELD_RC=0
  if [ "$FIX" -eq 1 ]; then
    run npx ecc-agentshield scan --fix || AGENTSHIELD_RC=$?
  else
    run npx ecc-agentshield scan || AGENTSHIELD_RC=$?
  fi
  if [ "$AGENTSHIELD_RC" -ne 0 ]; then
    echo "  WARN AgentShield exited $AGENTSHIELD_RC; continuing configuration health checks"
  fi
else
  echo "  SKIP: npx not available for agentshield"
  echo "  Install: npm install -g npx"
fi

echo ""
echo "=== Configuration Health ==="

check_symlink() {
  local name="$1" path="$2"
  if [ -L "$path" ]; then
    local target
    target="$(readlink "$path")"
    if [ -e "$target" ]; then
      echo "  OK   $name → $target"
    else
      echo "  BROKEN $name → $target (missing)"
    fi
  elif [ -f "$path" ] || [ -d "$path" ]; then
    echo "  COPY $name (not a symlink)"
  else
    echo "  MISS $name (not found)"
  fi
}

echo ""
echo "--- Claude Code ---"
check_symlink "12-rules.md" "$CLAUDE_RULES_12"
check_symlink "rules/common" "$CLAUDE_RULES_COMMON"
check_symlink "rules/python" "$CLAUDE_RULES_PYTHON"
if [ -f "$CLAUDE_SETTINGS" ]; then
  echo "  OK   settings.json"
else
  echo "  MISS settings.json"
fi
check_first_line "CLAUDE.md order" "$HOME/.claude/CLAUDE.md" '@12-rules.md'
check_contains "Claude MCP CBM" "$CLAUDE_MCP_JSON" 'codebase-memory-mcp'
check_contains "Claude MCP context7" "$CLAUDE_MCP_JSON" 'context7'
check_contains "Claude MCP x-docs" "$CLAUDE_MCP_JSON" 'x-docs'

echo ""
echo "--- Codex ---"
if [ -f "$CODEX_HOOKS" ]; then
  echo "  OK   hooks.json"
fi
if [ -d "$CODEX_SKILLS_DIR/caveman" ]; then
  echo "  OK   caveman skill installed"
else
  echo "  MISS caveman skill"
fi
check_contains "AGENTS.md 12-rules ref" "$CODEX_AGENTS" '12-rules.md'
check_contains "AGENTS.md context-mode SOP" "$CODEX_AGENTS" '## Context Mode SOP'
check_contains "config.toml CBM" "$CODEX_TOML" 'mcp_servers.codebase-memory-mcp'
check_contains "config.toml CBM search_graph approval" "$CODEX_TOML" 'mcp_servers.codebase-memory-mcp.tools.search_graph'
check_contains "config.toml context7" "$CODEX_TOML" 'mcp_servers.context7'
check_contains "config.toml x-docs" "$CODEX_TOML" 'mcp_servers.x-docs'
check_contains "config.toml context-mode" "$CODEX_TOML" 'mcp_servers.context-mode'
check_contains "config.toml context-mode ctx_stats approval" "$CODEX_TOML" 'mcp_servers.context-mode.tools.ctx_stats'
check_contains "config.toml context-mode ctx_search approval" "$CODEX_TOML" 'mcp_servers.context-mode.tools.ctx_search'
check_contains "config.toml context-mode ctx_index approval" "$CODEX_TOML" 'mcp_servers.context-mode.tools.ctx_index'
check_contains "config.toml context-mode ctx_doctor approval" "$CODEX_TOML" 'mcp_servers.context-mode.tools.ctx_doctor'
check_contains "hooks.json context-mode SOP reminder" "$CODEX_HOOKS" 'CONTEXT-MODE SOP:'
check_contains "quality gate manifest" "$BOOTSTRAP/agent/quality-gates/manifest.jsonc" '"events"'
check_contains "quality gate runner" "$BOOTSTRAP/scripts/agent-quality-gate.sh" 'agent_quality_gate.py'
check_contains "neat-freak adapter" "$BOOTSTRAP/scripts/neat-freak-gate.sh" 'check|apply'
check_contains "knowledge record adapter" "$BOOTSTRAP/scripts/knowledge-record-gate.sh" 'record-push'
if [ "$(git -C "$BOOTSTRAP/.." config --get core.hooksPath 2>/dev/null || true)" = "template/agent/quality-gates/hooks" ]; then
  echo "  OK   core.hooksPath -> template/agent/quality-gates/hooks"
else
  echo "  MISS core.hooksPath quality gate hooks"
fi
if grep -q 'QUALITY GATE PRE-' "$CODEX_HOOKS" 2>/dev/null; then
  echo "  WARN legacy Codex quality gate prompt hooks still present"
else
  echo "  OK   no legacy Codex quality gate prompt hooks"
fi

echo ""
echo "--- OpenCode ---"
if [ -f "$OPENCODE_CONFIG" ]; then
  echo "  OK   opencode.json"
fi
if [ -d "$OPENCODE_PLUGINS_DIR/caveman" ]; then
  echo "  OK   caveman plugin"
fi
check_contains "AGENTS.md generated marker" "$OPENCODE_AGENTS" 'Generated by install-agent-tooling.sh'
check_contains "opencode CBM" "$OPENCODE_CONFIG" 'codebase-memory-mcp'
check_contains "opencode context7" "$OPENCODE_CONFIG" 'context7'
check_contains "opencode x-docs" "$OPENCODE_CONFIG" 'x-docs'
  check_contains "AGENTS.md RTK" "$OPENCODE_AGENTS" '## RTK'
check_max_lines "AGENTS.md length" "$OPENCODE_AGENTS" 60

echo ""
echo "--- Pi ---"
if command -v pi &>/dev/null; then
  echo "  OK   pi binary ($(command -v pi))"
  if [ -f "$PI_SETTINGS" ]; then
    echo "  OK   settings.json"
  else
    echo "  MISS settings.json"
  fi
  check_contains "settings.json RTK extension" "$PI_SETTINGS" 'rtk.ts'
  check_contains "settings.json local provider extension" "$PI_SETTINGS" 'local-openai-provider.ts'
  check_contains "settings.json pi-mcp-extension package" "$PI_SETTINGS" 'pi-mcp-extension'
  check_contains "mcp.json CBM" "$PI_MCP_JSON" 'codebase-memory-mcp'
  check_contains "mcp.json context7" "$PI_MCP_JSON" 'context7'
  check_contains "mcp.json x-docs" "$PI_MCP_JSON" 'x-docs'
  if [ -f "$PI_LOCAL_PROVIDER" ]; then
    echo "  OK   local-openai-provider.ts"
  else
    echo "  MISS local-openai-provider.ts"
  fi
  if [ -f "$PI_MODELS_JSON" ]; then
    MODEL_COUNT=$(python3 - "$PI_MODELS_JSON" <<'PYEOF' 2>/dev/null || echo "?"
import json, sys
d = json.load(open(sys.argv[1]))
print(sum(len(p.get('models',[])) for p in d.get('providers',{}).values()))
PYEOF
)
    echo "  OK   models.json ($MODEL_COUNT models, used by /model picker in session)"
  else
    echo "  MISS models.json (run: scripts/install-agent-tooling.sh --configure)"
  fi
  if [ -d "$PI_SKILLS_DIR" ]; then
    SKILL_COUNT=$(find -L "$PI_SKILLS_DIR" -mindepth 2 -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')
    echo "  OK   skills/ ($SKILL_COUNT SKILL.md files)"
  fi
  if [ -f "$PI_AGENTS" ]; then
    if grep -q '12-rules' "$PI_AGENTS" 2>/dev/null; then
      echo "  OK   AGENTS.md (12-rules reference)"
    else
      echo "  MISS 12-rules in AGENTS.md"
    fi
  else
    echo "  MISS AGENTS.md"
  fi
  check_contains "AGENTS.md RTK" "$PI_AGENTS" '## RTK'
  check_max_lines "AGENTS.md length" "$PI_AGENTS" 60
  EXT_LIST=$(pi list 2>/dev/null || true)
  if echo "$EXT_LIST" | grep -q "rtk.ts"; then
    echo "  OK   RTK extension registered"
  else
    echo "  MISS RTK extension (run: pi install ~/.pi/agent/extensions/rtk.ts)"
  fi
  if echo "$EXT_LIST" | grep -q "pi-mcp-extension"; then
    echo "  OK   pi-mcp-extension package installed"
  else
    echo "  MISS pi-mcp-extension package"
  fi
fi

echo ""
echo "--- Reasonix ---"
if command -v reasonix &>/dev/null; then
  echo "  OK   reasonix binary"
  if [ -f "$REASONIX_CONFIG" ]; then
    echo "  OK   config.json"
  else
    echo "  MISS config.json"
  fi
  check_contains "config.json CBM" "$REASONIX_CONFIG" 'codebase-memory-mcp'
  check_contains "config.json context7" "$REASONIX_CONFIG" 'context7'
  check_contains "config.json x-docs" "$REASONIX_CONFIG" 'x-docs'
  if [ -d "$REASONIX_SKILLS_DIR" ]; then
    SKILL_COUNT=$(find "$REASONIX_SKILLS_DIR" -name '*.md' | wc -l | tr -d ' ')
    echo "  OK   skills/ ($SKILL_COUNT skill files)"
  fi
fi

echo ""
echo "--- Antigravity ---"
if command -v agy &>/dev/null; then
  echo "  OK   agy binary ($(command -v agy))"
  if [ -f "$ANTIGRAVITY_SETTINGS" ]; then
    echo "  OK   settings.json"
  else
    echo "  MISS settings.json"
  fi
  check_contains "mcp_config.json CBM" "$ANTIGRAVITY_MCP_JSON" 'codebase-memory-mcp'
  check_contains "mcp_config.json context7" "$ANTIGRAVITY_MCP_JSON" 'context7'
  check_contains "mcp_config.json x-docs" "$ANTIGRAVITY_MCP_JSON" 'x-docs'
  if [ -d "$ANTIGRAVITY_SKILLS_DIR" ]; then
    SKILL_COUNT=$(find -L "$ANTIGRAVITY_SKILLS_DIR" -mindepth 2 -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')
    echo "  OK   skills/ ($SKILL_COUNT SKILL.md files)"
  else
    echo "  MISS skills/"
  fi
fi

echo ""
echo "--- Workspace Context ---"
check_contains "work AGENTS 12-rules" "$WORK_AGENTS" '12-rules.md'
check_contains "work AGENTS RTK" "$WORK_AGENTS" 'RTK.md'
check_contains "global GEMINI.md RTK" "$GLOBAL_GEMINI" '## RTK'
check_contains "global GEMINI.md 12-rules" "$GLOBAL_GEMINI" '## 12 Rules Summary'
check_max_lines "global GEMINI.md length" "$GLOBAL_GEMINI" 60
check_contains "GEMINI.md RTK" "$WORK_GEMINI" '## RTK'
check_contains "GEMINI.md 12-rules" "$WORK_GEMINI" '## 12 Rules Summary'
check_max_lines "work GEMINI.md length" "$WORK_GEMINI" 60
check_contains "REASONIX.md RTK" "$WORK_REASONIX" '## RTK'
check_contains "REASONIX.md 12-rules" "$WORK_REASONIX" '## 12 Rules Summary'
check_max_lines "REASONIX.md length" "$WORK_REASONIX" 60

echo ""
echo "--- Upstream Skills ---"
AGENT_SKILLS="$(json_get_path shared.upstream_skills_root)"
if [ -d "$AGENT_SKILLS/upstream/ecc" ]; then
  ECC_COUNT=$(find "$AGENT_SKILLS/upstream/ecc" -maxdepth 2 -name SKILL.md | wc -l | tr -d ' ')
  echo "  OK   ECC skills: $ECC_COUNT"
else
  echo "  MISS ECC (run: make agent-sync)"
fi
if [ -d "$AGENT_SKILLS/upstream/mattpocock" ]; then
  POC_COUNT=$(find "$AGENT_SKILLS/upstream/mattpocock" -maxdepth 2 -name SKILL.md | wc -l | tr -d ' ')
  echo "  OK   Matt Pocock skills: $POC_COUNT"
else
  echo "  MISS Matt Pocock (run: make agent-sync)"
fi
if [ -d "$CLAUDE_SKILLS_DIR" ] || [ -d "$(json_get_path shared.cross_agent_skills_dir)" ]; then
  echo "  OK   cross-agent skill links present"
else
  echo "  MISS cross-agent skill links"
fi

echo ""
echo "--- Prompt Library ---"
PROMPT_LIBRARY="$(json_get_path shared.prompt_library_root)"
if [ -x "$HOME/.local/bin/agent-prompt" ]; then
  echo "  OK   agent-prompt helper"
else
  echo "  MISS agent-prompt helper (run: make agent-tools)"
fi
if [ -x "$HOME/.local/bin/agent-prompt-mcp" ]; then
  echo "  OK   agent-prompt-mcp helper"
else
  echo "  MISS agent-prompt-mcp helper (run: make agent-tools)"
fi
if [ -f "$PROMPT_LIBRARY/index.json" ]; then
  PROMPT_COUNT=$(grep -c '"id":' "$PROMPT_LIBRARY/index.json" 2>/dev/null || true)
  echo "  OK   prompt index: $PROMPT_COUNT records"
else
  echo "  MISS prompt index (run: make prompt-sync)"
fi

echo ""
echo "--- Agent Tools ---"
for tool in rtk context-mode codebase-memory-mcp; do
  if command -v "$tool" &>/dev/null; then
    echo "  OK   $tool ($(command -v "$tool"))"
  else
    echo "  MISS $tool"
  fi
done
# Check context7 (npx package, not a standalone binary)
if command -v npx &>/dev/null; then
  # Check if at least one agent has context7 MCP configured
  if grep -q 'context7' "$CLAUDE_MCP_JSON" 2>/dev/null || \
     grep -q 'context7' "$CODEX_TOML" 2>/dev/null || \
     grep -q 'context7' "$OPENCODE_CONFIG" 2>/dev/null || \
     grep -q 'context7' "$PI_MCP_JSON" 2>/dev/null || \
     grep -q 'context7' "$ANTIGRAVITY_MCP_JSON" 2>/dev/null; then
    echo "  OK   context7 MCP (configured in agent configs)"
  else
    echo "  MISS context7 MCP (not configured in any agent)"
  fi
fi
npm_packages_file="$BOOTSTRAP/agent/npm-global-packages.txt"
if [ -f "$npm_packages_file" ] && command -v npm &>/dev/null && command -v node &>/dev/null; then
  installed_json=$(npm -g ls --depth=0 --json 2>/dev/null || true)
  if [ -z "$installed_json" ]; then
    installed_json='{}'
  fi
  while IFS= read -r package; do
    [ -n "$package" ] || continue
    if printf '%s' "$installed_json" | node -e 'const fs=require("fs"); const pkg=process.argv[1]; const data=JSON.parse(fs.readFileSync(0,"utf8")||"{}"); process.exit((data.dependencies||{})[pkg] ? 0 : 1);' "$package"; then
      echo "  OK   npm global $package"
    else
      echo "  MISS npm global $package (run: make npm-packages)"
    fi
  done < <(grep -vE '^\s*(#|$)' "$npm_packages_file")
elif [ -f "$npm_packages_file" ]; then
  echo "  MISS npm globals prerequisite (install Node/npm before make npm-packages)"
fi

# Verify CBM indexed
if codebase-memory-mcp cli list_projects '{}' 2>/dev/null | grep -q '"name"'; then
  echo "  OK   CBM graph (indexed projects found)"
else
  echo "  MISS CBM graph (run: codebase-memory-mcp cli index_repository '{\"repo_path\": \"'\"$PWD\"'\"}')"
fi

echo ""
echo "Done."
