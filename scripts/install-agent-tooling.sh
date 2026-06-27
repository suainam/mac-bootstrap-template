#!/usr/bin/env bash
set -euo pipefail

CONFIGURE=0
DRY_RUN=0
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOOTSTRAP="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST="$BOOTSTRAP/agent/agent-manifest.json"

. "$BOOTSTRAP/scripts/lib/agent-shared.sh"
. "$BOOTSTRAP/scripts/lib/agent-manifest.sh"
. "$BOOTSTRAP/scripts/lib/skill-wiring.sh"
. "$BOOTSTRAP/scripts/lib/agent-mcp.sh"
. "$BOOTSTRAP/scripts/lib/agent-configure.sh"

usage() {
  cat <<'EOF'
Usage: scripts/install-agent-tooling.sh [options]

Install and wire agent-facing token/context tools.
Single source of truth for all agent configuration.

Options:
  --configure    Modify user-level agent config for detected agents.
  --dry-run      Print commands without running them.
  -h, --help     Show this help.

Configuration performed with --configure:
  - Symlink canonical files (12-rules, skills, rules) from bootstrap repo
  - rtk init for Claude/Codex/OpenCode/Pi
  - Claude Code context-mode + caveman plugins
  - Codex context-mode MCP + hooks
  - Codex skills + hooks for caveman
  - OpenCode AGENTS.md generation + plugins
  - Caveman ultra mode (default)
  - codebase-memory-mcp MCP
  - context7 docs MCP (for library documentation queries)
  - agent-prompt helper for local prompt-library lookup
  - Pi RTK extension
  - AgentShield security scan integration
  - Instinct/continuous learning skeleton
  - Package manager detection setup
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --configure) CONFIGURE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --with-cbm-ui) echo "  --with-cbm-ui is deprecated" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

CONTEXT7_KEY="${CONTEXT7_API_KEY:-}"

RULES_FILE="$(canonical_path canonical.rules_file)"
RULES_COMMON_SRC="$(canonical_path canonical.rules_common_dir)"
RULES_PYTHON_SRC="$(canonical_path canonical.rules_python_dir)"
PI_LOCAL_PROVIDER_SRC="$(canonical_path canonical.personal_extensions_dir)/local-openai-provider.ts"

CLAUDE_RULES_12="$(json_get_path agents.claude.paths.rules_12)"
CLAUDE_RULES_COMMON="$(json_get_path agents.claude.paths.rules_common)"
CLAUDE_RULES_PYTHON="$(json_get_path agents.claude.paths.rules_python)"
CLAUDE_SETTINGS="$(json_get_path agents.claude.paths.settings)"
CLAUDE_MCP_JSON="$(json_get_path agents.claude.paths.mcp)"
CLAUDE_MD="$(json_get_path agents.claude.paths.instructions)"
CLAUDE_SKILLS_DIR="$(json_get_path agents.claude.paths.skills)"

CODEX_TOML="$(json_get_path agents.codex.paths.config)"
CODEX_AGENTS="$(json_get_path agents.codex.paths.instructions)"
CODEX_HOOKS="$(json_get_path agents.codex.paths.hooks)"
CODEX_SKILLS_DIR="$(json_get_path agents.codex.paths.skills)"

OPENCODE_CONFIG="$(json_get_path agents.opencode.paths.config)"
OPENCODE_AGENTS="$(json_get_path agents.opencode.paths.instructions)"
OPENCODE_SKILLS_DIR="$(json_get_path agents.opencode.paths.skills)"
OPENCODE_PLUGINS_DIR="$(json_get_path agents.opencode.paths.plugins)"

PI_SETTINGS="$(json_get_path agents.pi.paths.settings)"
PI_MCP_JSON="$(json_get_path agents.pi.paths.mcp)"
PI_MODELS_JSON="$(json_get_path agents.pi.paths.models_json)"
PI_AGENTS_MD="$(json_get_path agents.pi.paths.instructions)"
PI_SKILLS_DIR="$(json_get_path agents.pi.paths.skills)"
PI_EXTENSIONS_DIR="$(json_get_path agents.pi.paths.extensions)"
PI_LOCAL_PROVIDER="$(json_get_path agents.pi.paths.local_provider_extension)"

REASONIX_CONFIG="$(json_get_path agents.reasonix.paths.config)"
REASONIX_SETTINGS="$(json_get_path agents.reasonix.paths.settings)"
REASONIX_SKILLS_DIR="$(json_get_path agents.reasonix.paths.skills)"

ANTIGRAVITY_SETTINGS="$(json_get_path agents.antigravity.paths.settings)"
ANTIGRAVITY_MCP_JSON="$(json_get_path agents.antigravity.paths.mcp)"
ANTIGRAVITY_SKILLS_DIR="$(json_get_path agents.antigravity.paths.skills)"
ANTIGRAVITY_HOOKS="$(json_get_path agents.antigravity.paths.hooks)"

SHARED_SKILLS_ROOT="$(json_get_path shared.upstream_skills_root)"
PROMPT_LIBRARY_ROOT="$(json_get_path shared.prompt_library_root)"
CROSS_AGENT_SKILLS_DIR="$(json_get_path shared.cross_agent_skills_dir)"
SKILL_DISTRIBUTION_FILE="$BOOTSTRAP/agent/skills-distribution.json"
WORK_ROOT="${WORK_ROOT:-$HOME/work}"
WORK_AGENTS="$WORK_ROOT/AGENTS.md"
WORK_GEMINI="$WORK_ROOT/GEMINI.md"
WORK_REASONIX="$WORK_ROOT/REASONIX.md"
GLOBAL_GEMINI="$HOME/.gemini/GEMINI.md"
CLAUDE_RTK="$HOME/.claude/RTK.md"
CODEX_RTK="$HOME/.codex/RTK.md"
PI_LIST_OK=0
RTK_SOURCE=""

log_agent_binaries

if [ "$CONFIGURE" -eq 0 ]; then
  echo "Skip config changes. Re-run with --configure to wire hooks/plugins/MCP."
  exit 0
fi

print_step_header "Step 1 — Canonical symlinks"
link_canonical_symlinks

print_step_header "Step 2 — Agent dirs"
ensure_agent_dirs

print_step_header "Step 2a — Workspace context files"
generate_workspace_context_files

print_step_header "Step 2b — Wire upstream skills into agents"
wire_upstream_skills_step

print_step_header "Step 2c — Prompt library helper"
configure_prompt_library_step

print_step_header "Step 3 — RTK"
configure_rtk_step

print_step_header "Step 4 — Context Mode"
configure_context_mode_step

print_step_header "Step 5 — Caveman"
configure_caveman_step

print_step_header "Step 6 — Code Review Graph + Context7 MCP"
ensure_code_review_graph
if [ -z "$CONTEXT7_KEY" ]; then
  echo "  NOTE: CONTEXT7_API_KEY not set — context7 may have rate limits"
fi

print_step_header "Step 7 — MCP config for all agents"
configure_all_mcp

print_step_header "Step 8 — OpenCode AGENTS.md"
generate_opencode_agents_doc

print_step_header "Step 9 — CLAUDE.md entry"
ensure_claude_instructions

print_step_header "Step 10 — Codex AGENTS.md entry"
ensure_codex_instructions

print_step_header "Step 10b — Pi Terminal Agent"
configure_pi_step

print_step_header "Step 11 — Reasonix (DeepSeek Agent)"
configure_reasonix_step

print_step_header "Step 11b — Antigravity CLI"
configure_antigravity_step

print_step_header "Step 12 — Security scan (AgentShield)"
configure_security_scan_step

echo ""
echo "=== Done ==="
echo "Run 'make doctor' or 'scripts/agent-doctor.sh' to verify."
