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
  - code-review-graph MCP + graph build
  - context7 docs MCP (for library documentation queries)
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
    --with-cbm-ui) echo "  --with-cbm-ui is deprecated (CBM replaced by code-review-graph)" ;;
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

# ─── Pre-flight checks ─────────────────────────────────
echo "=== Agent tool binaries ==="
for tool in rtk context-mode claude codex opencode; do
  if have "$tool"; then
    run "$tool" --version < /dev/null 2>&1 | head -1 || echo "  $tool: version check skipped"
  else
    echo "  missing: $tool"
  fi
done
if have pi; then
  run pi --version < /dev/null 2>&1 | head -1 || echo "  pi: installed"
fi

if [ "$CONFIGURE" -eq 0 ]; then
  echo "Skip config changes. Re-run with --configure to wire hooks/plugins/MCP."
  exit 0
fi

echo ""
echo "=== Step 1 — Canonical symlinks ==="
echo "  Source: $BOOTSTRAP"

run mkdir -p "$(dirname "$CLAUDE_RULES_12")"
run ln -sf "$RULES_FILE" "$CLAUDE_RULES_12"
echo "  LINK  $CLAUDE_RULES_12 → $RULES_FILE"

for pair in \
  "$RULES_COMMON_SRC:$CLAUDE_RULES_COMMON" \
  "$RULES_PYTHON_SRC:$CLAUDE_RULES_PYTHON"; do
  src="${pair%%:*}"
  dst="${pair#*:}"
  run mkdir -p "$(dirname "$dst")" "$src"
  if [ -L "$dst" ]; then
    run rm "$dst"
  elif [ -d "$dst" ] && [ ! -L "$dst" ]; then
    echo "  SKIP  $dst exists as real dir (remove manually to symlink)"
    continue
  fi
  run ln -sf "$src" "$dst"
  echo "  LINK  $dst → $src"
done

echo ""
echo "=== Step 2 — Agent dirs ==="
run mkdir -p "$(dirname "$CLAUDE_SETTINGS")" "$(dirname "$CODEX_TOML")" \
  "$(dirname "$OPENCODE_CONFIG")" "$(dirname "$PI_SETTINGS")" \
  "$(dirname "$REASONIX_CONFIG")" "$(dirname "$ANTIGRAVITY_SETTINGS")" \
  "$HOME/.agent/instincts/active" "$HOME/.agent/instincts/archived" \
  "$HOME/.agent/artifacts"

echo ""
echo "=== Step 2a — Workspace context files ==="
write_reference_file "$WORK_AGENTS" "@$CLAUDE_RULES_12" "@$CODEX_RTK"
echo "  Workspace AGENTS.md refs ensured"

RTK_SOURCE="$(pick_rtk_source)"
write_markdown_file "$WORK_GEMINI" "$(render_runtime_rules_doc "Global Antigravity Workspace Rules" "$RTK_SOURCE")"
echo "  Workspace GEMINI.md generated"
write_markdown_file "$GLOBAL_GEMINI" "$(render_runtime_rules_doc "Global Antigravity Rules" "$RTK_SOURCE")"
echo "  Global GEMINI.md generated"
write_markdown_file "$WORK_REASONIX" "$(render_runtime_rules_doc "Global Reasonix Workspace Rules" "$RTK_SOURCE")"
echo "  Workspace REASONIX.md generated"

echo ""
echo "=== Step 2b — Wire upstream skills into agents ==="
AGENT_SKILLS="$SHARED_SKILLS_ROOT"
if [ -d "$AGENT_SKILLS/upstream" ]; then
  run mkdir -p "$CLAUDE_SKILLS_DIR" "$CODEX_SKILLS_DIR" \
    "$CROSS_AGENT_SKILLS_DIR" "$PI_SKILLS_DIR" "$REASONIX_SKILLS_DIR" \
    "$OPENCODE_SKILLS_DIR" "$ANTIGRAVITY_SKILLS_DIR"

  # Remove legacy cc-switch-managed Claude skill links so bootstrap remains
  # the only shared skill distributor.
  if [ -d "$CLAUDE_SKILLS_DIR" ]; then
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
          "$HOME/.cc-switch/skills/"*)
            run rm -f "$legacy_path"
            echo "  Removed legacy Claude skill link: $legacy"
            ;;
        esac
      fi
    done
  fi

  echo "  ECC skills → agents"
  wire_skill_tree "$AGENT_SKILLS/upstream/ecc"

  echo "  Matt Pocock skills → agents"
  wire_skill_tree "$AGENT_SKILLS/upstream/mattpocock"

  echo "  Khazix skills → agents"
  if [ -d "$AGENT_SKILLS/upstream/khazix" ]; then
    wire_skill_tree "$AGENT_SKILLS/upstream/khazix"
  fi

  echo "  Personal skills → agents"
  if [ -d "$AGENT_SKILLS/personal" ]; then
    wire_skill_tree "$AGENT_SKILLS/personal"
  fi

  # OpenCode: add @-references in AGENTS.md
  append_opencode_upstream_skills "$OPENCODE_AGENTS"
else
  echo "  SKIP: run 'make agent-sync' first to clone upstream skills"
fi

echo ""
echo "=== Step 3 — RTK ==="
if have rtk; then
  try_run rtk init --global --auto-patch
  have codex   && try_run rtk init --global --codex
  have opencode && try_run rtk init --global --opencode --auto-patch
  have pi      && try_run rtk init --global --agent pi
else
  echo "  SKIP: rtk not installed"
fi

echo ""
echo "=== Step 4 — Context Mode ==="
if have context-mode && have claude; then
  run claude plugin marketplace add mksglu/context-mode
  run claude plugin install context-mode@context-mode
  try_run context-mode upgrade
fi

if have context-mode && have opencode; then
  opencode_config="$OPENCODE_CONFIG"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY-RUN: update OpenCode plugin list in $opencode_config"
  else
    node - "$opencode_config" <<'NODE'
const fs = require("fs"), path = process.argv[2];
let data = {};
if (fs.existsSync(path)) { const r = fs.readFileSync(path,"utf8").trim(); if (r) data=JSON.parse(r); }
const pl = Array.isArray(data.plugin) ? data.plugin : [];
for (const p of ["context-mode","./plugins/rtk.ts","./plugins/caveman/plugin.js"])
  if (!pl.includes(p)) pl.push(p);
data.plugin = pl;
fs.writeFileSync(path, JSON.stringify(data,null,2)+"\n");
NODE
  fi
  echo "  OpenCode plugins configured"
fi

echo ""
echo "=== Step 5 — Caveman ==="
# Run official caveman installer for Claude + OpenCode
if have node && have npx; then
  try_run npx -y github:JuliusBrussee/caveman -- --only claude --only opencode --non-interactive

  # Set caveman ultra as default (merge, don't overwrite)
  run mkdir -p "$HOME/.config/caveman"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY-RUN: merge caveman config with defaultMode=ultra"
  else
    node - "$HOME/.config/caveman/config.json" <<'NODE'
const fs = require("fs"), path = process.argv[2];
let cfg = {};
if (fs.existsSync(path)) {
  try { const r = fs.readFileSync(path,"utf8").trim(); if (r) cfg = JSON.parse(r); } catch {}
}
cfg.defaultMode = cfg.defaultMode || "ultra";
cfg.savingsDisplay = cfg.savingsDisplay !== undefined ? cfg.savingsDisplay : true;
cfg.rtkIntegration = cfg.rtkIntegration !== undefined ? cfg.rtkIntegration : true;
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
console.log("  Caveman config merged (defaultMode=" + cfg.defaultMode + ")");
NODE
  fi

  # Normalize hardcoded Cellar node paths in settings.json (survives Homebrew upgrades)
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY-RUN: normalize Cellar node paths in ~/.claude/settings.json"
  else
    node - "$HOME/.claude/settings.json" <<'NODE'
const fs = require("fs"), path = process.argv[1];
if (!fs.existsSync(path)) process.exit(0);
const data = JSON.parse(fs.readFileSync(path, "utf8"));
const HARDCODED = /\/opt\/homebrew\/Cellar\/node\/[^/]+\/bin\/node/g;
function fixCmd(obj) {
  if (!obj || typeof obj !== "object") return;
  if (Array.isArray(obj)) { obj.forEach(fixCmd); return; }
  if (obj.command && HARDCODED.test(obj.command)) {
    obj.command = obj.command.replace(HARDCODED, "/opt/homebrew/bin/node");
  }
  if (obj.hooks) obj.hooks.forEach(fixCmd);
}
if (data.hooks) Object.values(data.hooks).forEach(fixCmd);
const json = JSON.stringify(data, null, 2) + "\n";
if (json !== JSON.stringify(JSON.parse(fs.readFileSync(path,"utf8")), null, 2) + "\n") {
  fs.writeFileSync(path, json);
  console.log("  Normalized Cellar node paths in settings.json");
}
NODE
  fi

  # Codex: install caveman skills + hooks
  if have codex; then
    CAVEMAN_CACHE="$HOME/.claude/plugins/cache/caveman/caveman"
    CAVEMAN_SRC=""
    for d in "$CAVEMAN_CACHE"/*/skills; do
      [ -d "$d" ] && CAVEMAN_SRC="$d" && break
    done
    if [ -n "$CAVEMAN_SRC" ]; then
      for skill in caveman caveman-commit caveman-compress caveman-help caveman-review caveman-stats cavecrew; do
        run mkdir -p "$CODEX_SKILLS_DIR/$skill"
        run cp "$CAVEMAN_SRC/$skill/SKILL.md" "$CODEX_SKILLS_DIR/$skill/SKILL.md"
      done
      echo "  Codex caveman skills installed"
    else
      echo "  WARN: caveman skill source not found in plugin cache"
    fi

    # Add caveman hooks to Codex hooks.json
    if [ -f "$CODEX_HOOKS" ]; then
      node - "$CODEX_HOOKS" <<'NODE'
const fs = require("fs"), path = process.argv[2];
const hooks = JSON.parse(fs.readFileSync(path,"utf8"));
hooks.hooks = hooks.hooks || {};

const cavemanHook = {
  "matcher": "startup|resume",
  "hooks": [{
    "type": "command",
    "command": "echo 'CAVEMAN MODE ACTIVE (ultra). Drop articles/filler/pleasantries/hedging. Fragments OK. Abbreviate prose. Use arrows for causality. Code/commits/security: write normal. User says stop caveman or normal mode to deactivate.'",
    "timeout": 5,
    "statusMessage": "Loading caveman mode..."
  }]
};

const contextModeSopHook = {
  "matcher": "startup|resume",
  "hooks": [{
    "type": "command",
    "command": "echo 'CONTEXT-MODE SOP: CRG first for code discovery. Use ctx_batch_execute for parallel capture, ctx_search for follow-up, ctx_execute/ctx_execute_file for filtering and counts. Avoid curl/wget/rsync in bash.'",
    "timeout": 5,
    "statusMessage": "Loading context-mode SOP..."
  }]
};

function ensureSessionStartHook(entry, marker, addedMsg, existsMsg) {
  const ss = hooks.hooks.SessionStart || [];
  const exists = ss.some(e =>
    e.matcher === entry.matcher &&
    Array.isArray(e.hooks) &&
    e.hooks.some(h => h.command && h.command.includes(marker))
  );
  if (!exists) {
    ss.push(entry);
    hooks.hooks.SessionStart = ss;
    console.log(addedMsg);
    return true;
  }
  console.log(existsMsg);
  return false;
}

const changed = [
  ensureSessionStartHook(
    cavemanHook,
    "CAVEMAN MODE ACTIVE",
    "  Added caveman hook to Codex hooks.json",
    "  Caveman hook already in Codex hooks.json"
  ),
  ensureSessionStartHook(
    contextModeSopHook,
    "CONTEXT-MODE SOP:",
    "  Added context-mode SOP hook to Codex hooks.json",
    "  Context-mode SOP hook already in Codex hooks.json"
  ),
].some(Boolean);

if (changed) {
  fs.writeFileSync(path, JSON.stringify(hooks, null, 2) + "\n");
}
NODE
    fi
  fi

  # Pi: create caveman skill (doc path: ~/.pi/agent/skills/<name>/SKILL.md)
  if have pi && [ ! -f "$PI_SKILLS_DIR/caveman/SKILL.md" ]; then
    run mkdir -p "$PI_SKILLS_DIR/caveman"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "DRY-RUN: write $PI_SKILLS_DIR/caveman/SKILL.md"
    else
      cat > "$PI_SKILLS_DIR/caveman/SKILL.md" <<'PISKILL'
---
name: caveman
description: Talk terse. Drop articles, filler, pleasantries, hedging.
---
Talk terse. Drop articles/filler/pleasantries/hedging.
Fragments OK. Short synonyms. Technical terms exact.
Active by default. Off only: "normal mode" or "stop caveman".
PISKILL
    fi
    echo "  Pi caveman skill written"
  fi

  if have agy && [ ! -f "$ANTIGRAVITY_SKILLS_DIR/caveman/SKILL.md" ]; then
    run mkdir -p "$ANTIGRAVITY_SKILLS_DIR/caveman"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "DRY-RUN: write $ANTIGRAVITY_SKILLS_DIR/caveman/SKILL.md"
    else
      cat > "$ANTIGRAVITY_SKILLS_DIR/caveman/SKILL.md" <<'AGYSKILL'
---
name: caveman
description: Talk terse. Drop articles, filler, pleasantries, hedging.
---
Talk terse. Drop articles/filler/pleasantries/hedging.
Fragments OK. Short synonyms. Technical terms exact.
Active by default. Off only: "normal mode" or "stop caveman".
AGYSKILL
    fi
    echo "  Antigravity: caveman skill written"
  fi
fi

echo ""
echo "=== Step 6 — Code Review Graph + Context7 MCP ==="
# Ensure code-review-graph is installed via uv (isolated venv)
if ! have code-review-graph; then
  if have uv; then
    run uv tool install code-review-graph
  else
    echo "  SKIP: uv not installed — cannot install code-review-graph"
  fi
fi

# Determine context7 command (use API key from env if set)
if [ -n "$CONTEXT7_KEY" ]; then
  CTX7_CMD="npx -y @upstash/context7-mcp --api-key $CONTEXT7_KEY"
else
  echo "  NOTE: CONTEXT7_API_KEY not set — context7 may have rate limits"
  CTX7_CMD="npx -y @upstash/context7-mcp"
fi

echo ""
echo "=== Step 7 — MCP config for all agents ==="
RULES_FILE="$BOOTSTRAP/agent/rules/12-rules.md"

_context7_args() {
  if [ -n "$CONTEXT7_KEY" ]; then
    echo "[\"npx\",\"-y\",\"@upstash/context7-mcp\",\"--api-key\",\"$CONTEXT7_KEY\"]"
  else
    echo "[\"npx\",\"-y\",\"@upstash/context7-mcp\"]"
  fi
}

write_json_file() {
  local path="$1" code="$2"
  run mkdir -p "$(dirname "$path")"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY-RUN: write JSON config $path"
  else
    node - "$path" "$CONTEXT7_KEY" "$code" <<'NODE'
const fs = require("fs");
const { execSync } = require("child_process");
const path = process.argv[2];
const key = process.argv[3] || "";
const code = process.argv[4];

const getContext7Config = (key) => {
  let isGlobal = false;
  let command = "npx";
  let args = ["-y", "@upstash/context7-mcp"];
  try {
    isGlobal = execSync("command -v context7-mcp", { encoding: "utf8", stdio: [] }).trim() !== "";
    if (isGlobal) {
      command = execSync("command -v context7-mcp", { encoding: "utf8" }).trim();
      args = [];
    }
  } catch (e) {}
  if (key) {
    args.push("--api-key", key);
  }
  const cfg = { command, args };
  const proxy = process.env.HTTP_PROXY || process.env.http_proxy || "";
  if (proxy) {
    cfg.env = {
      NODE_USE_ENV_PROXY: "1",
      HTTP_PROXY: proxy,
      HTTPS_PROXY: process.env.HTTPS_PROXY || process.env.https_proxy || proxy,
      http_proxy: proxy,
      https_proxy: process.env.HTTPS_PROXY || process.env.https_proxy || proxy,
      ALL_PROXY: process.env.ALL_PROXY || proxy
    };
  }
  return cfg;
};

const fn = new Function("fs", "path", "key", "getContext7Config", code);
fn(fs, path, key, getContext7Config);
NODE
  fi
}

# --- Claude Code (user-level ~/.claude.json) ---
if [ -f "$CLAUDE_MCP_JSON" ]; then
  write_json_file "$CLAUDE_MCP_JSON" '
let cfg = {};
if (fs.existsSync(path)) {
  const raw = fs.readFileSync(path, "utf8").trim();
  if (raw) cfg = JSON.parse(raw);
}
if (!cfg.mcpServers) cfg.mcpServers = {};
delete cfg.mcpServers["codebase-memory-mcp"];
cfg.mcpServers["code-review-graph"] = { command: "code-review-graph", args: ["serve"] };
cfg.mcpServers["context7"] = getContext7Config(key);
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Claude Code: CRG + context7 MCP configured"
fi

if [ -f "$CODEX_TOML" ]; then
  if have context7-mcp; then
    CTX7_CMD_PATH="$(command -v context7-mcp)"
  else
    CTX7_CMD_PATH="npx"
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY-RUN: rewrite managed MCP stanzas in $CODEX_TOML"
  else
    TMP_BLOCK="$(mktemp)"
    RENDER_ARGS=(--context7-command "$CTX7_CMD_PATH")
    if [ -n "$CONTEXT7_KEY" ]; then
      RENDER_ARGS+=(--context7-api-key "$CONTEXT7_KEY")
    fi
    python3 "$BOOTSTRAP/scripts/render-codex-mcp-block.py" \
      "${RENDER_ARGS[@]}" > "$TMP_BLOCK"
    python3 "$BOOTSTRAP/scripts/sync-codex-mcp-config.py" "$CODEX_TOML" "$TMP_BLOCK"
    rm -f "$TMP_BLOCK"
  fi
  echo "  Codex: context-mode + CRG + context7 MCP configured"
fi

# --- OpenCode (~/.config/opencode/opencode.json) ---
if [ -f "$OPENCODE_CONFIG" ]; then
  write_json_file "$OPENCODE_CONFIG" '
let cfg = {};
if (fs.existsSync(path)) {
  const raw = fs.readFileSync(path, "utf8").trim();
  if (raw) cfg = JSON.parse(raw);
}
if (!cfg.mcp) cfg.mcp = {};
delete cfg.mcp["codebase-memory-mcp"];
cfg.mcp["code-review-graph"] = { enabled: true, type: "local", command: ["code-review-graph", "serve"] };
const c7 = getContext7Config(key);
cfg.mcp["context7"] = { enabled: true, type: "local", command: [c7.command].concat(c7.args) };
if (c7.env) cfg.mcp["context7"].env = c7.env;
fs.writeFileSync(path, JSON.stringify(cfg, null, 4) + "\n");
'
  echo "  OpenCode: CRG + context7 MCP configured"
fi

echo ""
echo "=== Step 8 — OpenCode AGENTS.md ==="
if [ -f "$RULES_FILE" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY-RUN: regenerate $OPENCODE_AGENTS from canonical rules"
  else
    cat > "$OPENCODE_AGENTS" <<AGENTSMD
<!-- Generated by install-agent-tooling.sh — do not edit manually -->
<!-- Edit canonical source at $BOOTSTRAP/agent/rules/12-rules.md -->

# OpenCode Runtime Rules

## 12 Rules Summary

Think before coding. Prefer the simplest working change. Read before write.
Touch only what is necessary. Match local conventions. Verify with tests.
Checkpoint progress. Fail loud on uncertainty or skipped work.

## RTK

Use \`rtk\` for shell commands when available.
Canonical RTK reference: \`$RTK_SOURCE\`

## CRG First

Prefer \`code-review-graph\` / \`context7\` before grep for code discovery.
Use grep only for literals, configs, or when MCP coverage is insufficient.

Canonical sources:
- \`$RULES_FILE\`
- \`$RTK_SOURCE\`
AGENTSMD
  fi
  echo "  OpenCode AGENTS.md generated"
fi

echo ""
echo "=== Step 9 — CLAUDE.md entry ==="
write_reference_file "$CLAUDE_MD" "@12-rules.md" "@RTK.md"
echo "  CLAUDE.md ordered: 12-rules first, RTK second"

echo ""
echo "=== Step 10 — Codex AGENTS.md entry ==="
if [ -f "$CODEX_AGENTS" ]; then
  if ! grep -q '12-rules.md' "$CODEX_AGENTS" 2>/dev/null; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "DRY-RUN: append 12-rules ref to $CODEX_AGENTS"
    else
      echo -e '\n@'"$HOME"'/.claude/12-rules.md' >> "$CODEX_AGENTS"
    fi
    echo "  Added 12-rules ref"
  else
    echo "  12-rules ref already present"
  fi

  CODEX_CRG_BLOCK='<!-- codebase-memory-mcp:start -->
# Codebase Knowledge Graph (code-review-graph)

This setup uses code-review-graph as the current graph MCP. It replaces the
legacy codebase-memory-mcp tool names. Prefer MCP graph tools before
grep/glob/file-search for code discovery.

## Priority Order
1. `get_minimal_context_tool` - compact repo/task context
2. `traverse_graph_tool` - find and follow functions/classes/files
3. `get_review_context_tool` - review diffs with snippets and impact
4. `get_impact_radius_tool` - understand blast radius
5. `get_architecture_overview_tool` / `list_communities_tool` - architecture view

## Context Mode SOP
- Start with `ctx_batch_execute(commands, queries)` for parallel capture and same-roundtrip search
- Use `ctx_search([...])` for follow-up questions against indexed output and session memory
- Use `ctx_execute` / `ctx_execute_file` to filter, count, parse, or aggregate; print only derived results
- Use bash for short fixed observations or state mutation, not large-output analysis
- Avoid `curl` / `wget` / `rsync` in bash; use `ctx_execute(language: "shell", code: "...")` instead

## When to fall back to grep/glob
- Searching for string literals, error messages, config values
- Searching non-code files (Dockerfiles, shell scripts, configs)
- When MCP tools return insufficient results
<!-- codebase-memory-mcp:end -->'
  replace_managed_block "$CODEX_AGENTS" '<!-- codebase-memory-mcp:start -->' '<!-- codebase-memory-mcp:end -->' "$CODEX_CRG_BLOCK"
  echo "  Codex AGENTS.md graph guidance aligned with code-review-graph"
fi

echo ""
echo "=== Step 10 — Pi Terminal Agent ==="
if have pi; then
  run mkdir -p "$PI_SKILLS_DIR" "$PI_EXTENSIONS_DIR"

  if [ -f "$PI_LOCAL_PROVIDER_SRC" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "DRY-RUN: copy $PI_LOCAL_PROVIDER_SRC -> $PI_LOCAL_PROVIDER"
    else
      cp -f "$PI_LOCAL_PROVIDER_SRC" "$PI_LOCAL_PROVIDER"
    fi
    echo "  Pi: local provider extension staged"
  fi

  # Read Pi package list from canonical file
  PI_PACKAGES_FILE="$BOOTSTRAP/agent/pi-packages.txt"
  PI_PKG_LIST=()
  if [ -f "$PI_PACKAGES_FILE" ]; then
    while IFS= read -r _pkg; do
      PI_PKG_LIST+=("$_pkg")
    done < <(grep -vE '^\s*(#|$)' "$PI_PACKAGES_FILE")
  fi
  PI_PKG_JSON=$(printf '%s\n' "${PI_PKG_LIST[@]}" | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))' 2>/dev/null || echo '[]')

  PI_INSTALLED=""
  if PI_INSTALLED="$(capture_with_timeout 5 pi list 2>/dev/null)"; then
    PI_LIST_OK=1
  else
    echo "  WARN: 'pi list' failed or timed out — skipping Pi package/extension registration"
  fi
  if [ "$PI_LIST_OK" -eq 1 ]; then
    for _pkg in "${PI_PKG_LIST[@]}"; do
      pname="${_pkg#npm:}"
      if echo "$PI_INSTALLED" | grep -q "$pname"; then
        echo "  SKIP: $pname already installed"
      else
        run pi install "$_pkg"
        echo "  Pi: $pname installed"
      fi
    done
  fi

  write_markdown_file "$PI_AGENTS_MD" "$(render_runtime_rules_doc "Global Pi Coding Agent Rules" "$RTK_SOURCE")"
  echo "  Pi: AGENTS.md generated"

  PI_PKG_JSON_ESC=$(printf '%s\n' "$PI_PKG_JSON" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo '[]')
  write_json_file "$PI_SETTINGS" "
let cfg = {};
if (fs.existsSync(path)) {
  const raw = fs.readFileSync(path, 'utf8').trim();
  if (raw) cfg = JSON.parse(raw);
}
const extensionPath = process.env.HOME + '/.pi/agent/extensions/rtk.ts';
const localProviderPath = process.env.HOME + '/.pi/agent/extensions/local-openai-provider.ts';
const skillsPath = process.env.HOME + '/.pi/agent/skills';
const pkgList = JSON.parse($PI_PKG_JSON_ESC);
cfg.packages = Array.isArray(cfg.packages) ? cfg.packages : [];
for (const p of pkgList) {
  if (!cfg.packages.includes(p)) cfg.packages.push(p);
}
cfg.extensions = Array.isArray(cfg.extensions) ? cfg.extensions : [];
if (!cfg.extensions.includes(extensionPath)) cfg.extensions.push(extensionPath);
if (!cfg.extensions.includes(localProviderPath)) cfg.extensions.push(localProviderPath);
cfg.skills = Array.isArray(cfg.skills) ? cfg.skills : [];
if (!cfg.skills.includes(skillsPath)) cfg.skills.push(skillsPath);
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + '\n');
"
  echo "  Pi: settings.json updated"

  write_json_file "$PI_MCP_JSON" '
const cfg = {
  mcpServers: {
    "code-review-graph": { command: "code-review-graph", args: ["serve"] },
    "context7": getContext7Config(key)
  }
};
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Pi: mcp.json updated"

  # Generate models.json from live local OpenAI-compatible server.
  # Pi reads this file inside sessions via /model — NOT via --list-models CLI flag.
  # (--list-models only lists built-in providers + auth.json entries.)
  PI_LOCAL_BASE_URL="${PI_LOCAL_PROVIDER_BASE_URL:-http://localhost:20128/v1}"
  SKIP_MODELS="asr|tts|voiceclone|voicedesign|omni"
  if curl -sf --max-time 3 "$PI_LOCAL_BASE_URL/models" -o /tmp/pi_models_raw.json 2>/dev/null && [ -s /tmp/pi_models_raw.json ]; then
    python3 - "$PI_MODELS_JSON" "$PI_LOCAL_BASE_URL" "$SKIP_MODELS" < /tmp/pi_models_raw.json <<'PY'
import json, re, sys
from pathlib import Path

dst, base_url, skip_pat = Path(sys.argv[1]), sys.argv[2], re.compile(sys.argv[3])
payload = sys.stdin.read().strip()
if not payload:
    print(f"  Pi: models endpoint returned empty payload from {base_url} — models.json unchanged")
    raise SystemExit(0)

try:
    raw = json.loads(payload)
except json.JSONDecodeError:
    print(f"  Pi: models endpoint returned invalid JSON from {base_url} — models.json unchanged")
    raise SystemExit(0)

models = [{"id": m["id"]} for m in raw.get("data", []) if not skip_pat.search(m["id"])]
config = {
    "providers": {
        "local-openai": {
            "name": "Local OpenAI-Compatible (RTK proxy)",
            "baseUrl": base_url,
            "api": "openai-completions",
            "apiKey": "local",
            "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": False},
            "models": models,
        }
    }
}
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps(config, indent=2) + "\n")
print(f"  Pi: models.json written ({len(models)} models from {base_url})")
PY
  else
    echo "  Pi: local server $PI_LOCAL_BASE_URL offline or empty — models.json unchanged"
  fi
  rm -f /tmp/pi_models_raw.json

  RTK_PI_FILE="$PI_EXTENSIONS_DIR/rtk.ts"
  if [ -f "$RTK_PI_FILE" ] && [ "$PI_LIST_OK" -eq 1 ]; then
    REGISTERED=$(printf '%s\n' "$PI_INSTALLED" | grep -c "extensions/rtk.ts" || true)
    if [ "$REGISTERED" -eq 0 ]; then
      run pi install "$RTK_PI_FILE"
      echo "  Pi: RTK extension registered"
    fi
  fi
else
  echo "  Pi not installed — skipping"
fi

echo ""
echo "=== Step 11 — Reasonix (DeepSeek Agent) ==="
if have reasonix; then
  run mkdir -p "$REASONIX_SKILLS_DIR"

  write_json_file "$REASONIX_CONFIG" '
let cfg = {};
if (fs.existsSync(path)) {
  const raw = fs.readFileSync(path, "utf8").trim();
  if (raw) cfg = JSON.parse(raw);
}
if (cfg.skipSetup === undefined) cfg.skipSetup = false;
if (!cfg.mcpServers) cfg.mcpServers = {};
delete cfg.mcpServers["codebase-memory-mcp"];
delete cfg.mcpServers["codebase-memory"];
cfg.mcpServers["code-review-graph"] = { command: "code-review-graph", args: ["serve"] };
cfg.mcpServers["context7"] = getContext7Config(key);
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Reasonix: config.json merged with CRG + context7 MCP"

  # 12-rules is NOT a skill — it's appended to CLAUDE.md/AGENTS.md as instructions.
  # Reasonix reads ~/.claude/CLAUDE.md which already has @12-rules.md via Step 8.
  # No skill file needed.

  # Caveman skill for reasonix
  if [ ! -f "$REASONIX_SKILLS_DIR/caveman.md" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "DRY-RUN: write $REASONIX_SKILLS_DIR/caveman.md"
    else
      cat > "$REASONIX_SKILLS_DIR/caveman.md" <<'RSKILL'
# Caveman Mode for Reasonix

Talk terse. Drop articles/filler/pleasantries/hedging.
Fragments OK. Short synonyms. Technical terms exact.
Active by default. Off only: "normal mode" or "stop caveman".
RSKILL
    fi
    echo "  Reasonix: caveman skill installed"
  fi

  echo "  NOTE: Run 'reasonix setup' first-time to complete token/provider config"
else
  echo "  Reasonix not installed — skipping"
fi

echo ""
echo "=== Step 11b — Antigravity CLI ==="
if have agy; then
  run mkdir -p "$(dirname "$ANTIGRAVITY_SETTINGS")" "$ANTIGRAVITY_SKILLS_DIR" "$(dirname "$ANTIGRAVITY_HOOKS")"
  write_json_file "$ANTIGRAVITY_SETTINGS" '
let cfg = {};
if (fs.existsSync(path)) {
  const raw = fs.readFileSync(path, "utf8").trim();
  if (raw) cfg = JSON.parse(raw);
}
cfg.skills = Array.isArray(cfg.skills) ? cfg.skills : [];
const skillsPath = process.env.HOME + "/.gemini/antigravity-cli/skills";
if (!cfg.skills.includes(skillsPath)) cfg.skills.push(skillsPath);
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Antigravity: settings.json updated"

  write_json_file "$ANTIGRAVITY_MCP_JSON" '
const cfg = {
  mcpServers: {
    "code-review-graph": { command: "code-review-graph", args: ["serve"] },
    "context7": getContext7Config(key)
  }
};
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Antigravity: mcp_config.json updated"
else
  echo "  Antigravity not installed — skipping"
fi

echo ""
echo "=== Step 12 — Security scan (AgentShield) ==="
if have npm; then
  # Pre-cache agentshield so first scan is fast
  try_run npm list -g ecc-agentshield 2>/dev/null || \
    echo "  AgentShield available via npx ecc-agentshield"
fi

echo ""
echo "=== Done ==="
echo "Run 'make doctor' or 'scripts/agent-doctor.sh' to verify."
