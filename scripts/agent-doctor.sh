#!/usr/bin/env bash
set -euo pipefail

# Agent health & security check
# Runs AgentShield scan + configuration verification

DRY_RUN=0
FIX=0
BOOTSTRAP="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$BOOTSTRAP/agent/agent-manifest.json"
PYTHON_BIN="${PYTHON:-$BOOTSTRAP/.venv/bin/python}"
source "$BOOTSTRAP/scripts/lib/agent-shared.sh"

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

CLAUDE_AGENTS_MD="$(json_get_path agents.claude.paths.agents_md)"
CLAUDE_MD="$(json_get_path agents.claude.paths.instructions)"
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


REASONIX_CONFIG="$(json_get_path agents.reasonix.paths.config)"
REASONIX_SKILLS_DIR="$(json_get_path agents.reasonix.paths.skills)"

ANTIGRAVITY_SETTINGS="$(json_get_path agents.antigravity.paths.settings)"
ANTIGRAVITY_MCP_JSON="$(json_get_path agents.antigravity.paths.mcp)"
ANTIGRAVITY_SKILLS_DIR="$(json_get_path agents.antigravity.paths.skills)"
GLOBAL_GEMINI="$(json_get_path agents.antigravity.paths.global_instructions)"

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
  shift 2
  if [ ! -f "$path" ]; then
    echo "  MISS $host MCP config"
    return 0
  fi
  if command -v context7-mcp >/dev/null 2>&1; then
    context7_command="$(command -v context7-mcp)"
  fi
  local -a audit_args=(
    "$BOOTSTRAP/scripts/agent_mcp_runtime.py"
    audit
    --host "$host"
    --path "$path"
    --bootstrap "$BOOTSTRAP"
    --context7-command "$context7_command"
  )
  if [ "$host" = "codex" ]; then
    audit_args+=(--policy "$BOOTSTRAP/agent/mcp-policy.json")
  fi
  audit_args+=(--check-executables "$@")
  if output="$("$PYTHON_BIN" "${audit_args[@]}" 2>&1)"; then
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

find_agentshield_baseline() {
  local candidate
  for candidate in \
    "$BOOTSTRAP/../private/agent/agentshield.baseline.json" \
    "$BOOTSTRAP/../../private/agent/agentshield.baseline.json" \
    "$BOOTSTRAP/../../../private/agent/agentshield.baseline.json"
  do
    if [ -f "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

scan_agentshield() {
  local baseline scan_dir scan_baseline scan_result scan_rc=0 verify_rc=0
  baseline="$(find_agentshield_baseline || true)"
  if [ -z "$baseline" ]; then
    echo "  WARN AgentShield baseline missing: private/agent/agentshield.baseline.json"
    return 0
  fi
  if ! command -v ecc-agentshield &>/dev/null && ! npx --no-install ecc-agentshield --version &>/dev/null; then
    echo "  SKIP: ecc-agentshield not installed (optional security scan)"
    return 0
  fi

  scan_dir="$(mktemp -d)"
  trap 'rm -rf -- "$scan_dir"; trap - RETURN INT TERM HUP' RETURN
  trap 'rm -rf -- "$scan_dir"; exit 130' INT TERM HUP
  scan_baseline="$scan_dir/baseline.json"
  local -a scan_args=(
    --no-install ecc-agentshield scan
    --path "$HOME/.claude"
    --format json
    --min-severity high
    --save-baseline "$scan_baseline"
  )
  if [ "$FIX" -eq 1 ]; then
    scan_args+=(--fix)
  fi
  npx "${scan_args[@]}" >/dev/null 2>/dev/null || scan_rc=$?

  if [ ! -s "$scan_baseline" ] || { [ "$scan_rc" -ne 0 ] && [ "$scan_rc" -ne 2 ]; }; then
    echo "  WARN AgentShield scan failed (exit $scan_rc)"
    return 0
  fi

  scan_result="$("$PYTHON_BIN" "$BOOTSTRAP/scripts/verify-agentshield-baseline.py" "$scan_baseline" "$baseline" 2>&1)" || verify_rc=$?
  if [ "$verify_rc" -eq 0 ]; then
    echo "  INFO AgentShield acknowledged findings unchanged (${scan_result#acknowledged=})"
  elif [ "$verify_rc" -eq 1 ]; then
    echo "  WARN AgentShield new or changed findings"
    while IFS= read -r line; do
      [ -n "$line" ] && echo "       $line"
    done <<EOF
$scan_result
EOF
  else
    echo "  WARN AgentShield baseline verification failed"
    [ -n "$scan_result" ] && echo "       $scan_result"
  fi
}

echo "=== Agent Security Scan ==="
if command -v npx &>/dev/null; then
  scan_agentshield
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
    if [ -e "$path" ]; then
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
check_symlink "AGENTS.md" "$CLAUDE_AGENTS_MD"
check_symlink "CLAUDE.md → AGENTS.md" "$CLAUDE_MD"
check_symlink "rules/common" "$CLAUDE_RULES_COMMON"
check_symlink "rules/python" "$CLAUDE_RULES_PYTHON"
if [ -f "$CLAUDE_SETTINGS" ]; then
  echo "  OK   settings.json"
else
  echo "  MISS settings.json"
fi
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
if "$PYTHON_BIN" "$BOOTSTRAP/scripts/agent-instructions.py" verify \
  --target "$CODEX_AGENTS" \
  --rules "$BOOTSTRAP/agent/rules/AGENTS.md" \
  --rtk "$HOME/.codex/RTK.md" \
  --adversarial-review "$BOOTSTRAP/agent/rules/adversarial-review-gate.md"; then
  echo "  OK   AGENTS.md canonical rules content"
else
  echo "  MISS AGENTS.md canonical rules content"
fi
check_contains "AGENTS.md context-mode SOP" "$CODEX_AGENTS" '## Context Mode SOP'
if "$PYTHON_BIN" "$BOOTSTRAP/scripts/context7-mcp-bridge.py" --validate-private-config; then
  echo "  OK   Context7 private config and permissions"
else
  echo "  MISS Context7 private config or permissions"
fi
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
if [ -f "$OPENCODE_PLUGINS_DIR/rtk.ts" ]; then
  echo "  OK   OpenCode V2 RTK plugin"
else
  echo "  MISS OpenCode V2 RTK plugin"
fi
if grep -q '"plugin"[[:space:]]*:' "$OPENCODE_CONFIG" 2>/dev/null; then
  echo "  WARN legacy OpenCode plugin key remains"
fi
if grep -Eq '"@opencode-ai/plugin"' "$(dirname "$OPENCODE_CONFIG")/package.json" 2>/dev/null; then
  echo "  WARN legacy @opencode-ai/plugin dependency remains"
fi
check_contains "AGENTS.md generated marker" "$OPENCODE_AGENTS" 'Generated by install-agent-tooling.sh'
audit_mcp_config opencode "$OPENCODE_CONFIG"
check_contains "AGENTS.md RTK" "$OPENCODE_AGENTS" '## RTK'
check_contains "OpenCode AGENTS.md Adversarial Review" "$OPENCODE_AGENTS" 'Adversarial Review'
check_max_lines "AGENTS.md length" "$OPENCODE_AGENTS" 60

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

echo "--- Global Instructions & Antigravity ---"
check_symlink "global GEMINI.md → canonical AGENTS.md" "$GLOBAL_GEMINI"

OMP_AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.omp/agent}"
if [ -d "$OMP_AGENT_DIR" ] || command -v omp &>/dev/null; then
  check_symlink "OMP AGENTS.md" "$OMP_AGENT_DIR/AGENTS.md"
fi
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
if "$PYTHON_BIN" "$BOOTSTRAP/scripts/skill_supply_chain.py" check >/tmp/mac-bootstrap-skill-check.out 2>/tmp/mac-bootstrap-skill-check.err; then
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


# Verify CBM indexed
if codebase-memory-mcp cli list_projects '{}' 2>/dev/null | grep -q '"name"'; then
  echo "  OK   CBM graph (indexed projects found)"
else
  echo "  MISS CBM graph (run: codebase-memory-mcp cli index_repository '{\"repo_path\": \"'\"$PWD\"'\"}')"
fi

echo ""
echo "Done."
