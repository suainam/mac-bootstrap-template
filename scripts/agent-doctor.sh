#!/usr/bin/env bash
set -euo pipefail

# Agent health & security check
# Runs AgentShield scan + configuration verification

DRY_RUN=0
FIX=0
BOOTSTRAP="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$BOOTSTRAP/agent/agent-manifest.json"
source "$BOOTSTRAP/scripts/lib/agent-shared.sh"
load_x_mcp_private_env
load_devspace_mcp_private_env
export CONTEXT7_KEY="${CONTEXT7_KEY:-${CONTEXT7_API_KEY:-}}"

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

audit_mcp_config() {
  local host="$1" path="$2" context7_command="npx" output
  local -a policy_args=()
  shift 2
  if [ ! -f "$path" ]; then
    echo "  MISS $host MCP config"
    return 0
  fi
  if command -v context7-mcp >/dev/null 2>&1; then
    context7_command="$(command -v context7-mcp)"
  fi
  if [ "$host" = "codex" ]; then
    policy_args=(--policy "$BOOTSTRAP/agent/mcp-policy.json")
  fi
  if output="$(python3 "$BOOTSTRAP/scripts/agent_mcp_runtime.py" audit \
      --host "$host" \
      --path "$path" \
      --bootstrap "$BOOTSTRAP" \
      --context7-command "$context7_command" \
      "${policy_args[@]}" \
      --check-executables \
      "$@" 2>&1)"; then
    echo "  OK   $host managed MCP state"
  else
    echo "  MISS $host managed MCP state"
    while IFS= read -r line; do
      [ -n "$line" ] && echo "       $line"
    done <<EOF
$output
EOF
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
audit_mcp_config claude "$CLAUDE_MCP_JSON"

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
audit_mcp_config codex "$CODEX_TOML" --hooks-path "$CODEX_HOOKS"
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
audit_mcp_config opencode "$OPENCODE_CONFIG"
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
  audit_mcp_config pi "$PI_MCP_JSON"
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
  audit_mcp_config reasonix "$REASONIX_CONFIG"
  if [ -d "$REASONIX_SKILLS_DIR" ]; then
    SKILL_COUNT=$(find -L "$REASONIX_SKILLS_DIR" -maxdepth 2 \( -name 'SKILL.md' -o \( -maxdepth 1 -name '*.md' \) \) | wc -l | tr -d ' ')
    echo "  OK   skills/ ($SKILL_COUNT skill entrypoints)"
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
  audit_mcp_config antigravity "$ANTIGRAVITY_MCP_JSON"
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
echo "--- Skill Supply Chain ---"
if [ -f "$BOOTSTRAP/agent-skills/registry/sources.jsonc" ]; then
  echo "  OK   skills-sources.jsonc"
else
  echo "  MISS skills-sources.jsonc"
fi
if [ -f "$BOOTSTRAP/agent-skills/registry/targets.jsonc" ]; then
  echo "  OK   skill-targets.jsonc"
else
  echo "  MISS skill-targets.jsonc"
fi
if python3 "$BOOTSTRAP/scripts/skill_supply_chain.py" check >/tmp/mac-bootstrap-skill-check.out 2>/tmp/mac-bootstrap-skill-check.err; then
  sed 's/^/  OK   /' /tmp/mac-bootstrap-skill-check.out
else
  echo "  FAIL skill supply-chain check"
  sed 's/^/       /' /tmp/mac-bootstrap-skill-check.err
fi
if [ -d "$CLAUDE_SKILLS_DIR" ] || [ -d "$(json_get_path shared.cross_agent_skills_dir)" ]; then
  echo "  OK   agent skill dirs present"
else
  echo "  MISS agent skill dirs"
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

find_data_hub_runtime_config() {
  local candidate
  for candidate in \
    "$BOOTSTRAP/../private/agent/data_hub.runtime.jsonc" \
    "$BOOTSTRAP/../../private/agent/data_hub.runtime.jsonc" \
    "$BOOTSTRAP/../../../private/agent/data_hub.runtime.jsonc"
  do
    if [ -f "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

runtime_config_path="$(find_data_hub_runtime_config || true)"
if [ -n "$runtime_config_path" ]; then
  llm_wiki_info="$(python3 - "$runtime_config_path" <<'PY'
import json
import os
import shlex
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
lines = [line for line in text.splitlines() if not line.strip().startswith("//")]
data = json.loads("\n".join(lines) or "{}")
config = data.get("llm_wiki", {}) or {}

def as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)

enabled = as_bool(config.get("enabled", False))
api_base = str(config.get("api_base", "http://127.0.0.1:19828")).rstrip("/")
project_root = str(config.get("project_root", ""))
token_env = str(config.get("token_env", "LLM_WIKI_TOKEN"))
token = str(config.get("token", "")) or os.environ.get(token_env, "")
mcp = config.get("mcp", {}) or {}
local = config.get("local", {}) or {}
def emit(name, value):
    print(f"{name}={shlex.quote(str(value))}")

emit("enabled", str(enabled).lower())
emit("api_base", api_base)
emit("project_root", project_root)
emit("token_env", token_env)
emit("token_configured", str(bool(token)).lower())
emit("mcp_enabled", str(as_bool(mcp.get("enabled", False))).lower())
emit("local_build_required", str(as_bool(local.get("build_required", False))).lower())
PY
)"
  eval "$llm_wiki_info"
  if [ "${enabled:-false}" = "true" ]; then
    echo "  OK   llm_wiki enabled via API ($api_base)"

    if command -v curl &>/dev/null; then
      curl_args=(-fsS -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 4)
      if [ "${token_configured:-false}" = "true" ]; then
        token_value="${!token_env:-}"
        if [ -n "$token_value" ]; then
          curl_args+=(-H "Authorization: Bearer $token_value")
        fi
      fi
      api_status="$(curl "${curl_args[@]}" "$api_base/api/v1/projects" 2>/dev/null || true)"
      case "$api_status" in
        200|204)
          echo "  OK   llm_wiki API reachable"
          ;;
        401|403)
          echo "  WARN llm_wiki API reachable but protected ($api_status); configure $token_env for authenticated data-hub access if needed"
          ;;
        "")
          echo "  WARN llm_wiki API not reachable at $api_base; start LLM Wiki.app if data-hub needs live API context"
          ;;
        *)
          echo "  WARN llm_wiki API returned HTTP $api_status at $api_base"
          ;;
      esac
    else
      echo "  WARN curl missing; cannot probe llm_wiki API"
    fi

    if [ -d "/Applications/LLM Wiki.app" ]; then
      echo "  OK   LLM Wiki.app installed"
      if [ -f "/Applications/LLM Wiki.app/Contents/Resources/mcp-server/dist/src/index.js" ]; then
        echo "  INFO LLM Wiki.app bundled MCP server present (optional)"
      fi
    fi

    if [ "${mcp_enabled:-false}" = "true" ]; then
      if [ -f "/Applications/LLM Wiki.app/Contents/Resources/mcp-server/dist/src/index.js" ]; then
        echo "  OK   llm_wiki MCP server from app bundle"
      elif [ -f "${LLM_WIKI_DIR:-$HOME/work/llm_wiki}/mcp-server/dist/index.js" ]; then
        echo "  OK   llm_wiki MCP build artifact"
      else
        echo "  MISS llm_wiki MCP enabled but no MCP server artifact found (run: make llm-wiki-mcp-build)"
      fi
    else
      echo "  INFO llm_wiki MCP not required; data-hub uses API mode"
    fi

    if [ "${local_build_required:-false}" = "true" ]; then
      llm_wiki_dir="${LLM_WIKI_DIR:-$HOME/work/llm_wiki}"
      if [ -d "$llm_wiki_dir" ] && [ -f "$llm_wiki_dir/package.json" ]; then
        echo "  OK   llm_wiki source checkout ($llm_wiki_dir)"
      else
        echo "  MISS llm_wiki source checkout required (run: make llm-wiki-install)"
      fi
      if command -v node &>/dev/null && command -v npm &>/dev/null; then
        echo "  OK   llm_wiki Node/npm prerequisite"
      else
        echo "  MISS llm_wiki Node/npm prerequisite (install Node.js 20+)"
      fi
      if command -v cargo &>/dev/null; then
        echo "  OK   llm_wiki Rust prerequisite"
      else
        echo "  MISS llm_wiki Rust prerequisite (install Rust 1.70+)"
      fi
    fi
  fi
fi

# Verify CBM indexed
if codebase-memory-mcp cli list_projects '{}' 2>/dev/null | grep -q '"name"'; then
  echo "  OK   CBM graph (indexed projects found)"
else
  echo "  MISS CBM graph (run: codebase-memory-mcp cli index_repository '{\"repo_path\": \"'\"$PWD\"'\"}')"
fi

echo ""
echo "Done."
