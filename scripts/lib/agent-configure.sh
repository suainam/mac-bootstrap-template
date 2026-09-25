#!/usr/bin/env bash

print_step_header() {
  echo ""
  echo "=== $1 ==="
}

log_agent_binaries() {
  echo "=== Agent tool binaries ==="
  local tool
  for tool in rtk context-mode claude codex opencode; do
    if have "$tool"; then
      run "$tool" --version < /dev/null 2>&1 | head -1 || echo "  $tool: version check skipped"
    else
      echo "  missing: $tool"
    fi
  done
}

link_canonical_symlinks() {
  echo "  Source: $BOOTSTRAP"

  write_managed_symlink "$RULES_FILE" "$CLAUDE_AGENTS_MD"
  echo "  LINK  $CLAUDE_AGENTS_MD → $RULES_FILE"
  write_managed_symlink "$CLAUDE_AGENTS_MD" "$CLAUDE_MD"
  echo "  LINK  $CLAUDE_MD → $CLAUDE_AGENTS_MD (CLAUDE.md is now a symlink to AGENTS.md)"
  if [ -n "$CLAUDE_RULES_ADVERSARIAL_REVIEW" ] && [ -f "$ADVERSARIAL_REVIEW_SRC" ]; then
    run ln -sf "$ADVERSARIAL_REVIEW_SRC" "$CLAUDE_RULES_ADVERSARIAL_REVIEW"
    echo "  LINK  $CLAUDE_RULES_ADVERSARIAL_REVIEW → $ADVERSARIAL_REVIEW_SRC"
  fi


  local pair src dst
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
}

ensure_agent_dirs() {
  run mkdir -p "$(dirname "$CLAUDE_SETTINGS")" "$(dirname "$CODEX_TOML")" \
    "$(dirname "$OPENCODE_CONFIG")" "$(dirname "$PI_SETTINGS")" \
    "$(dirname "$REASONIX_CONFIG")" "$(dirname "$ANTIGRAVITY_SETTINGS")" \
    "$OPENCODE_PLUGINS_DIR" \
    "$HOME/.agent/instincts/active" "$HOME/.agent/instincts/archived" \
    "$HOME/.agent/artifacts"
}

configure_global_instruction_links() {
  write_managed_symlink "$RULES_FILE" "$GLOBAL_GEMINI"
  echo "  LINK  $GLOBAL_GEMINI → $RULES_FILE"
  local omp_agent_dir="${PI_CODING_AGENT_DIR:-$HOME/.omp/agent}"
  if [ -n "${PI_CODING_AGENT_DIR:-}" ] || [ -d "$omp_agent_dir" ] || have omp; then
    write_managed_symlink "$RULES_FILE" "$omp_agent_dir/AGENTS.md"
    echo "  LINK  $omp_agent_dir/AGENTS.md → $RULES_FILE"
  fi
}
wire_upstream_skills_step() {
  run python3 "$BOOTSTRAP/scripts/skill_supply_chain.py" distribute
}

configure_prompt_library_step() {
  run mkdir -p "$PROMPT_LIBRARY_ROOT" "$HOME/.local/bin"
  run ln -sf "$BOOTSTRAP/scripts/agent-prompt.sh" "$HOME/.local/bin/agent-prompt"
  run rm -f "$HOME/.local/bin/agent-prompt-mcp"
  echo "  LINK  $HOME/.local/bin/agent-prompt -> $BOOTSTRAP/scripts/agent-prompt.sh"

  if [ -f "$PROMPT_LIBRARY_ROOT/index.json" ]; then
    echo "  OK    prompt index present: $PROMPT_LIBRARY_ROOT/index.json"
  else
    echo "  SKIP  prompt index missing; run 'make prompt-sync'"
  fi
}

configure_rtk_step() {
  if have rtk; then
    try_run rtk init --global --auto-patch
    if have codex; then try_run rtk init --global --codex; fi
  else
    echo "  SKIP: rtk not installed"
  fi
}

configure_opencode_v2_step() {
  [ -f "$OPENCODE_RTK_PLUGIN" ] || return 0
  [ -f "$OPENCODE_CONFIG" ] || return 0
  run mkdir -p "$OPENCODE_PLUGINS_DIR"
  if [ -f "$OPENCODE_PLUGINS_DIR/rtk.ts" ] && [ ! -L "$OPENCODE_PLUGINS_DIR/rtk.ts" ]; then
    if ! cmp -s "$OPENCODE_RTK_PLUGIN" "$OPENCODE_PLUGINS_DIR/rtk.ts"; then
      run cp "$OPENCODE_RTK_PLUGIN" "$OPENCODE_PLUGINS_DIR/rtk.ts"
    fi
  else
    write_managed_symlink "$OPENCODE_RTK_PLUGIN" "$OPENCODE_PLUGINS_DIR/rtk.ts"
  fi
  if [ "${DRY_RUN:-0}" -eq 0 ]; then
    run npm uninstall --prefix "$(dirname "$OPENCODE_CONFIG")" --save @opencode-ai/plugin
    run npm install --prefix "$(dirname "$OPENCODE_CONFIG")" --save @opencode/plugin@2
  else
    echo "DRY-RUN: replace @opencode-ai/plugin with @opencode/plugin@2 in $(dirname "$OPENCODE_CONFIG")"
  fi
  if [ "${DRY_RUN:-0}" -eq 0 ]; then
    node - "$OPENCODE_CONFIG" <<'NODE'
const fs = require("fs"), path = process.argv[2];
let data = {};
if (fs.existsSync(path)) {
  const raw = fs.readFileSync(path, "utf8").trim();
  if (raw) data = JSON.parse(raw);
}
const legacy = Array.isArray(data.plugin) ? data.plugin : [];
const plugins = Array.isArray(data.plugins) ? data.plugins : [];
for (const entry of legacy) {
  const packageName = Array.isArray(entry) ? entry[0] : entry;
  if (packageName === "./plugins/rtk.ts") plugins.push(packageName);
}
if (!plugins.includes("./plugins/rtk.ts")) plugins.push("./plugins/rtk.ts");
data.plugins = [...new Set(plugins)];
delete data.plugin;
fs.writeFileSync(path, JSON.stringify(data, null, 2) + "\n");
NODE
  else
    echo "DRY-RUN: migrate OpenCode plugin config in $OPENCODE_CONFIG"
  fi
  echo "  OpenCode V2 RTK plugin configured"
}

configure_context_mode_step() {
  if have context-mode && have claude; then
    run claude plugin marketplace add mksglu/context-mode
    run claude plugin install context-mode@context-mode
    try_run context-mode upgrade
  fi
}

configure_caveman_step() {
  if ! have node || ! have npx; then
    return 0
  fi

  try_run npx -y github:JuliusBrussee/caveman -- --only claude --non-interactive

  run mkdir -p "$HOME/.config/caveman"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: merge caveman config with defaultMode=ultra"
  else
    node - "$HOME/.config/caveman/config.json" <<'NODE'
const fs = require("fs"), path = process.argv[2];
let cfg = {};
if (fs.existsSync(path)) {
  try {
    const r = fs.readFileSync(path, "utf8").trim();
    if (r) cfg = JSON.parse(r);
  } catch {}
}
cfg.defaultMode = cfg.defaultMode || "ultra";
cfg.savingsDisplay = cfg.savingsDisplay !== undefined ? cfg.savingsDisplay : true;
cfg.rtkIntegration = cfg.rtkIntegration !== undefined ? cfg.rtkIntegration : true;
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
console.log("  Caveman config merged (defaultMode=" + cfg.defaultMode + ")");
NODE
  fi

  if [ "${DRY_RUN:-0}" -eq 1 ]; then
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
if (json !== JSON.stringify(JSON.parse(fs.readFileSync(path, "utf8")), null, 2) + "\n") {
  fs.writeFileSync(path, json);
  console.log("  Normalized Cellar node paths in settings.json");
}
NODE
  fi

  install_codex_caveman_assets
  install_antigravity_caveman_skill
}

scrub_codex_context_mode_continuity_hooks() {
  [ -f "$CODEX_HOOKS" ] || return 0

  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: remove context-mode SessionStart/PreCompact hooks from $CODEX_HOOKS"
    return 0
  fi

  node - "$CODEX_HOOKS" <<'NODE'
const fs = require("fs"), path = process.argv[2];
const hooks = JSON.parse(fs.readFileSync(path, "utf8"));
if (!hooks.hooks || typeof hooks.hooks !== "object") process.exit(0);

const removals = new Map([
  ["SessionStart", "context-mode hook codex sessionstart"],
  ["PreCompact", "context-mode hook codex precompact"],
]);

let changed = false;
for (const [section, needle] of removals) {
  const entries = Array.isArray(hooks.hooks[section]) ? hooks.hooks[section] : [];
  const filtered = entries.filter((entry) => {
    const hookList = Array.isArray(entry?.hooks) ? entry.hooks : [];
    return !hookList.some((hook) => typeof hook?.command === "string" && hook.command.includes(needle));
  });
  if (filtered.length !== entries.length) {
    changed = true;
    if (filtered.length > 0) {
      hooks.hooks[section] = filtered;
    } else {
      delete hooks.hooks[section];
    }
  }
}

if (changed) {
  fs.writeFileSync(path, JSON.stringify(hooks, null, 2) + "\n");
  console.log("  Removed Codex context-mode SessionStart/PreCompact hooks");
}
NODE
}

install_codex_caveman_assets() {
  have codex || return 0

  local caveman_cache="$HOME/.claude/plugins/cache/caveman/caveman"
  local caveman_src="" d skill
  for d in "$caveman_cache"/*/skills; do
    [ -d "$d" ] && caveman_src="$d" && break
  done
  if [ -n "$caveman_src" ]; then
    for skill in caveman caveman-commit caveman-compress caveman-help caveman-review caveman-stats cavecrew; do
      run mkdir -p "$CODEX_SKILLS_DIR/$skill"
      run cp "$caveman_src/$skill/SKILL.md" "$CODEX_SKILLS_DIR/$skill/SKILL.md"
    done
    echo "  Codex caveman skills installed"
  else
    echo "  WARN: caveman skill source not found in plugin cache"
  fi

  [ -f "$CODEX_HOOKS" ] || return 0
  node - "$CODEX_HOOKS" <<'NODE'
const fs = require("fs"), path = process.argv[2];
const hooks = JSON.parse(fs.readFileSync(path, "utf8"));
hooks.hooks = hooks.hooks || {};

const cavemanHook = {
  matcher: "startup|resume",
  hooks: [{
    type: "command",
    command: "echo 'CAVEMAN MODE ACTIVE (ultra). Drop articles/filler/pleasantries/hedging. Fragments OK. Abbreviate prose. Use arrows for causality. Code/commits/security: write normal. User says stop caveman or normal mode to deactivate.'",
    timeout: 5,
    statusMessage: "Loading caveman mode..."
  }]
};

const contextModeSopHook = {
  matcher: "startup|resume",
  hooks: [{
    type: "command",
    command: "echo 'CONTEXT-MODE SOP: CRG first for code discovery. Use ctx_batch_execute for parallel capture, ctx_search for follow-up, ctx_execute/ctx_execute_file for filtering and counts. Avoid curl/wget/rsync in bash.'",
    timeout: 5,
    statusMessage: "Loading context-mode SOP..."
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

function removeUserPromptHooks(markers, removedMsg, missingMsg) {
  const ups = hooks.hooks.UserPromptSubmit || [];
  const filtered = ups.filter(e =>
    !Array.isArray(e.hooks) ||
    !e.hooks.some(h =>
      typeof h.command === "string" &&
      markers.some(marker => h.command.includes(marker))
    )
  );
  if (filtered.length !== ups.length) {
    if (filtered.length > 0) {
      hooks.hooks.UserPromptSubmit = filtered;
    } else {
      delete hooks.hooks.UserPromptSubmit;
    }
    console.log(removedMsg);
    return true;
  }
  console.log(missingMsg);
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
  removeUserPromptHooks(
    ["QUALITY GATE PRE-COMMIT", "QUALITY GATE PRE-PUSH"],
    "  Removed legacy quality gate prompt hooks from Codex hooks.json",
    "  No legacy quality gate prompt hooks in Codex hooks.json"
  ),
].some(Boolean);

if (changed) {
  fs.writeFileSync(path, JSON.stringify(hooks, null, 2) + "\n");
}
NODE

  scrub_codex_context_mode_continuity_hooks
}


install_antigravity_caveman_skill() {
  if ! have agy || [ -f "$ANTIGRAVITY_SKILLS_DIR/caveman/SKILL.md" ]; then
    return 0
  fi
  run mkdir -p "$ANTIGRAVITY_SKILLS_DIR/caveman"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
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
}

generate_opencode_agents_doc() {
  [ -f "$RULES_FILE" ] || return 0
  local rtk_source="${RTK_SOURCE:-$(pick_rtk_source)}"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: regenerate $OPENCODE_AGENTS from canonical rules"
  else
    cat > "$OPENCODE_AGENTS" <<AGENTSMD
<!-- Generated by install-agent-tooling.sh — do not edit manually -->
<!-- Edit canonical source at $BOOTSTRAP/agent/rules/AGENTS.md -->

# OpenCode Runtime Rules

## 12 Rules Summary

Think before coding. Prefer the simplest working change. Read before write.
Touch only what is necessary. Match local conventions. Verify with tests.
Checkpoint progress. Fail loud on uncertainty or skipped work.

## Adversarial Review Gate

Solidify all review findings into automated regression tests or audit gates. Never declare fixed on chat output alone without executable check evidence.

## RTK

Use \`rtk\` for shell commands when available.
Canonical RTK reference: \`$rtk_source\`

## CRG First

Prefer \`codebase-memory-mcp\` / \`context7\` before grep for code discovery.
Use grep only for literals, configs, or when MCP coverage is insufficient.

Canonical sources:
- \`$RULES_FILE\`
- \`$ADVERSARIAL_REVIEW_SRC\`
- \`$rtk_source\`
AGENTSMD
  fi
  echo "  OpenCode AGENTS.md generated"
}


ensure_codex_instructions() {
  local adv_arg=()
  local adv_src="${ADVERSARIAL_REVIEW_SRC:-$BOOTSTRAP/agent/rules/adversarial-review-gate.md}"
  if [ -n "$adv_src" ] && [ -f "$adv_src" ]; then
    adv_arg=(--adversarial-review "$adv_src")
  fi

  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: render canonical rules into $CODEX_AGENTS"
  else
    python3 "$BOOTSTRAP/scripts/agent-instructions.py" render \
      --target "$CODEX_AGENTS" --rules "$RULES_FILE" --rtk "$CODEX_RTK" \
      "${adv_arg[@]}"
  fi
  echo "  Codex canonical rules embedded"

  local codex_crg_block='<!-- codebase-memory-mcp:start -->
# Codebase Knowledge Graph (codebase-memory-mcp)

Prefer MCP graph tools before grep/glob/file-search for code discovery.

## Priority Order
1. `search_graph` - find functions/classes/routes by name pattern / semantic_query
2. `trace_path` - call chain traversal (inbound/outbound/both)
3. `get_code_snippet` - read source by qualified name
4. `get_architecture` - repo overview: languages, packages, routes, hotspots
5. `check_index_coverage` - verify index coverage before stating absence or dead code
6. `query_graph` - Cypher-like queries for complex patterns

## Context Mode SOP
- Start with `ctx_batch_execute(commands, queries)` for parallel capture and same-roundtrip search
- Use `ctx_search([...])` for follow-up questions against indexed output and session memory
- Use `ctx_execute` / `ctx_execute_file` to filter, count, parse, or aggregate; print only derived results
- Use bash for short fixed observations or state mutation, not large-output analysis
- Avoid `curl` / `wget` / `rsync` in bash; use `ctx_execute(language: "shell", code: "...")` instead

## Mandatory Threshold
- Do NOT run `glob` or `read` across broad code trees before running `search_graph` / `trace_path`.
- If a glob or grep would match >20 code files, stop and use CBM structural query tools.

## When to fall back to grep/glob
- Searching for string literals, error messages, config values
- Searching non-code files (Dockerfiles, shell scripts, configs)
- Verifying lines flagged by `check_index_coverage`
<!-- codebase-memory-mcp:end -->'
  replace_managed_block "$CODEX_AGENTS" '<!-- codebase-memory-mcp:start -->' '<!-- codebase-memory-mcp:end -->' "$codex_crg_block"
}

link_pi_private_configs() {
  [ -n "${PI_PRIVATE_CONFIG_DIR:-}" ] || return 0
  [ -d "$PI_PRIVATE_CONFIG_DIR" ] || return 0

  local name src dst
  for name in settings.json mcp.json models.json; do
    src="$PI_PRIVATE_CONFIG_DIR/$name"
    [ -e "$src" ] || continue
    dst="$HOME/.pi/agent/$name"
    if [ -L "$dst" ]; then
      run rm "$dst"
    elif [ -e "$dst" ]; then
      if [ ! -e "$src.pre-private" ]; then
        run mv "$dst" "$src.pre-private"
        echo "  Pi: preserved previous $name at $src.pre-private"
      else
        run rm "$dst"
      fi
    fi
    run ln -s "$src" "$dst"
    echo "  Pi: $dst -> $src"
  done

  local package_src package_dst
  package_src="$PI_PRIVATE_CONFIG_DIR/pi-cliproxyapi-provider"
  package_dst="$HOME/.pi/agent/pi-cliproxyapi-provider"
  run mkdir -p "$package_src"
  if [ -d "$package_dst" ] && [ ! -L "$package_dst" ]; then
    if [ -f "$package_dst/config.json" ] && [ ! -f "$package_src/config.json" ]; then
      run mv "$package_dst/config.json" "$package_src/config.json"
    fi
    run rm -rf "$package_dst"
  elif [ -L "$package_dst" ]; then
    run rm "$package_dst"
  fi
  run ln -s "$package_src" "$package_dst"
  echo "  Pi: $package_dst -> $package_src"
}


configure_reasonix_step() {
  if ! have reasonix; then
    echo "  Reasonix not installed — skipping"
    return 0
  fi

  run mkdir -p "$REASONIX_SKILLS_DIR"
  configure_reasonix_mcp

  if [ ! -f "$REASONIX_SKILLS_DIR/caveman/SKILL.md" ]; then
    if [ "${DRY_RUN:-0}" -eq 1 ]; then
      echo "DRY-RUN: write $REASONIX_SKILLS_DIR/caveman/SKILL.md"
    else
      mkdir -p "$REASONIX_SKILLS_DIR/caveman"
      cat > "$REASONIX_SKILLS_DIR/caveman/SKILL.md" <<'RSKILL'
# Caveman Mode for Reasonix

Talk terse. Drop articles/filler/pleasantries/hedging.
Fragments OK. Short synonyms. Technical terms exact.
Active by default. Off only: "normal mode" or "stop caveman".
RSKILL
      rm -f "$REASONIX_SKILLS_DIR/caveman.md"
    fi
    echo "  Reasonix: caveman skill installed"
  fi

  echo "  NOTE: Run 'reasonix setup' first-time to complete token/provider config"
}

configure_antigravity_step() {
  if ! have agy; then
    echo "  Antigravity not installed — skipping"
    return 0
  fi

  run mkdir -p "$(dirname "$ANTIGRAVITY_SETTINGS")" "$ANTIGRAVITY_SKILLS_DIR" "$(dirname "$ANTIGRAVITY_HOOKS")"
  configure_antigravity_settings_file
  configure_antigravity_mcp_file
}

configure_security_scan_step() {
  if have npm; then
    try_run npm list -g ecc-agentshield 2>/dev/null || \
      echo "  AgentShield available via npx ecc-agentshield"
  fi
}
