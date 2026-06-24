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
  if have pi; then
    run pi --version < /dev/null 2>&1 | head -1 || echo "  pi: installed"
  fi
}

link_canonical_symlinks() {
  echo "  Source: $BOOTSTRAP"

  run mkdir -p "$(dirname "$CLAUDE_RULES_12")"
  run ln -sf "$RULES_FILE" "$CLAUDE_RULES_12"
  echo "  LINK  $CLAUDE_RULES_12 → $RULES_FILE"

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
    "$HOME/.agent/instincts/active" "$HOME/.agent/instincts/archived" \
    "$HOME/.agent/artifacts"
}

generate_workspace_context_files() {
  write_reference_file "$WORK_AGENTS" "@$CLAUDE_RULES_12" "@$CODEX_RTK"
  echo "  Workspace AGENTS.md refs ensured"

  RTK_SOURCE="$(pick_rtk_source)"
  write_markdown_file "$WORK_GEMINI" "$(render_runtime_rules_doc "Global Antigravity Workspace Rules" "$RTK_SOURCE")"
  echo "  Workspace GEMINI.md generated"
  write_markdown_file "$GLOBAL_GEMINI" "$(render_runtime_rules_doc "Global Antigravity Rules" "$RTK_SOURCE")"
  echo "  Global GEMINI.md generated"
  write_markdown_file "$WORK_REASONIX" "$(render_runtime_rules_doc "Global Reasonix Workspace Rules" "$RTK_SOURCE")"
  echo "  Workspace REASONIX.md generated"
}

wire_upstream_skills_step() {
  local agent_skills="$SHARED_SKILLS_ROOT"
  if [ ! -d "$agent_skills/upstream" ]; then
    echo "  SKIP: run 'make agent-sync' first to clone upstream skills"
    return 0
  fi

  run mkdir -p "$CLAUDE_SKILLS_DIR" "$CODEX_SKILLS_DIR" \
    "$CROSS_AGENT_SKILLS_DIR" "$PI_SKILLS_DIR" "$REASONIX_SKILLS_DIR" \
    "$OPENCODE_SKILLS_DIR" "$ANTIGRAVITY_SKILLS_DIR"

  if [ -d "$CLAUDE_SKILLS_DIR" ]; then
    local legacy legacy_path target
    for legacy in cavecrew caveman caveman-commit caveman-compress caveman-help caveman-review caveman-stats; do
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
  wire_skill_tree "$agent_skills/upstream/ecc"

  echo "  Matt Pocock skills → agents"
  wire_skill_tree "$agent_skills/upstream/mattpocock"

  echo "  Khazix skills → agents"
  if [ -d "$agent_skills/upstream/khazix" ]; then
    wire_skill_tree "$agent_skills/upstream/khazix"
  fi

  echo "  Garden skills → agents"
  if [ -d "$agent_skills/upstream/garden" ]; then
    wire_skill_tree "$agent_skills/upstream/garden"
  fi

  echo "  Humanizer skills → agents"
  if [ -d "$agent_skills/upstream/humanizer" ]; then
    wire_skill_tree "$agent_skills/upstream/humanizer"
  fi

  echo "  Personal skills → agents"
  if [ -d "$agent_skills/personal" ]; then
    wire_skill_tree "$agent_skills/personal"
  fi

  append_opencode_upstream_skills "$OPENCODE_AGENTS"
}

configure_rtk_step() {
  if have rtk; then
    try_run rtk init --global --auto-patch
    have codex && try_run rtk init --global --codex
    have opencode && try_run rtk init --global --opencode --auto-patch
    have pi && try_run rtk init --global --agent pi
  else
    echo "  SKIP: rtk not installed"
  fi
}

configure_context_mode_step() {
  if have context-mode && have claude; then
    run claude plugin marketplace add mksglu/context-mode
    run claude plugin install context-mode@context-mode
    try_run context-mode upgrade
  fi

  if have context-mode && have opencode; then
    local opencode_config="$OPENCODE_CONFIG"
    if [ "${DRY_RUN:-0}" -eq 1 ]; then
      echo "DRY-RUN: update OpenCode plugin list in $opencode_config"
    else
      node - "$opencode_config" <<'NODE'
const fs = require("fs"), path = process.argv[2];
let data = {};
if (fs.existsSync(path)) {
  const r = fs.readFileSync(path, "utf8").trim();
  if (r) data = JSON.parse(r);
}
const pl = Array.isArray(data.plugin) ? data.plugin : [];
for (const p of ["context-mode", "./plugins/rtk.ts", "./plugins/caveman/plugin.js"]) {
  if (!pl.includes(p)) pl.push(p);
}
data.plugin = pl;
fs.writeFileSync(path, JSON.stringify(data, null, 2) + "\n");
NODE
    fi
    echo "  OpenCode plugins configured"
  fi
}

configure_caveman_step() {
  if ! have node || ! have npx; then
    return 0
  fi

  try_run npx -y github:JuliusBrussee/caveman -- --only claude --only opencode --non-interactive

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
  install_pi_caveman_skill
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

  scrub_codex_context_mode_continuity_hooks
}

install_pi_caveman_skill() {
  if ! have pi || [ -f "$PI_SKILLS_DIR/caveman/SKILL.md" ]; then
    return 0
  fi
  run mkdir -p "$PI_SKILLS_DIR/caveman"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
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
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
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
}

ensure_claude_instructions() {
  write_reference_file "$CLAUDE_MD" "@12-rules.md" "@RTK.md"
  echo "  CLAUDE.md ordered: 12-rules first, RTK second"
}

ensure_codex_instructions() {
  [ -f "$CODEX_AGENTS" ] || return 0

  if ! grep -q '12-rules.md' "$CODEX_AGENTS" 2>/dev/null; then
    if [ "${DRY_RUN:-0}" -eq 1 ]; then
      echo "DRY-RUN: append 12-rules ref to $CODEX_AGENTS"
    else
      echo -e '\n@'"$HOME"'/.claude/12-rules.md' >> "$CODEX_AGENTS"
    fi
    echo "  Added 12-rules ref"
  else
    echo "  12-rules ref already present"
  fi

  local codex_crg_block='<!-- codebase-memory-mcp:start -->
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
  replace_managed_block "$CODEX_AGENTS" '<!-- codebase-memory-mcp:start -->' '<!-- codebase-memory-mcp:end -->' "$codex_crg_block"
  echo "  Codex AGENTS.md graph guidance aligned with code-review-graph"
}

configure_pi_step() {
  if ! have pi; then
    echo "  Pi not installed — skipping"
    return 0
  fi

  run mkdir -p "$PI_SKILLS_DIR" "$PI_EXTENSIONS_DIR"

  if [ -f "$PI_LOCAL_PROVIDER_SRC" ]; then
    if [ "${DRY_RUN:-0}" -eq 1 ]; then
      echo "DRY-RUN: copy $PI_LOCAL_PROVIDER_SRC -> $PI_LOCAL_PROVIDER"
    else
      cp -f "$PI_LOCAL_PROVIDER_SRC" "$PI_LOCAL_PROVIDER"
    fi
    echo "  Pi: local provider extension staged"
  fi

  local pi_packages_file="$BOOTSTRAP/agent/pi-packages.txt"
  local pi_installed="" registered pname _pkg
  local pi_pkg_list=()
  if [ -f "$pi_packages_file" ]; then
    while IFS= read -r _pkg; do
      pi_pkg_list+=("$_pkg")
    done < <(grep -vE '^\s*(#|$)' "$pi_packages_file")
  fi
  local pi_pkg_json
  pi_pkg_json="$(printf '%s\n' "${pi_pkg_list[@]}" | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))' 2>/dev/null || echo "[]")"

  PI_LIST_OK=0
  if pi_installed="$(capture_with_timeout 5 pi list 2>/dev/null)"; then
    PI_LIST_OK=1
  else
    echo "  WARN: 'pi list' failed or timed out — skipping Pi package/extension registration"
  fi
  if [ "$PI_LIST_OK" -eq 1 ]; then
    for _pkg in "${pi_pkg_list[@]}"; do
      pname="${_pkg#npm:}"
      if echo "$pi_installed" | grep -q "$pname"; then
        echo "  SKIP: $pname already installed"
      else
        run pi install "$_pkg"
        echo "  Pi: $pname installed"
      fi
    done
  fi

  write_markdown_file "$PI_AGENTS_MD" "$(render_runtime_rules_doc "Global Pi Coding Agent Rules" "$RTK_SOURCE")"
  echo "  Pi: AGENTS.md generated"

  local pi_pkg_json_esc
  pi_pkg_json_esc="$(printf '%s\n' "$pi_pkg_json" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo '[]')"
  write_json_file "$PI_SETTINGS" "
let cfg = {};
if (fs.existsSync(path)) {
  const raw = fs.readFileSync(path, 'utf8').trim();
  if (raw) cfg = JSON.parse(raw);
}
const extensionPath = process.env.HOME + '/.pi/agent/extensions/rtk.ts';
const localProviderPath = process.env.HOME + '/.pi/agent/extensions/local-openai-provider.ts';
const skillsPath = process.env.HOME + '/.pi/agent/skills';
const pkgList = JSON.parse($pi_pkg_json_esc);
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

  configure_pi_mcp_file

  local pi_local_base_url="${PI_LOCAL_PROVIDER_BASE_URL:-http://localhost:20128/v1}"
  local skip_models="asr|tts|voiceclone|voicedesign|omni"
  if curl -sf --max-time 3 "$pi_local_base_url/models" -o /tmp/pi_models_raw.json 2>/dev/null && [ -s /tmp/pi_models_raw.json ]; then
    python3 - "$PI_MODELS_JSON" "$pi_local_base_url" "$skip_models" < /tmp/pi_models_raw.json <<'PY'
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
    echo "  Pi: local server $pi_local_base_url offline or empty — models.json unchanged"
  fi
  rm -f /tmp/pi_models_raw.json

  local rtk_pi_file="$PI_EXTENSIONS_DIR/rtk.ts"
  if [ -f "$rtk_pi_file" ] && [ "$PI_LIST_OK" -eq 1 ]; then
    registered="$(printf '%s\n' "$pi_installed" | grep -c "extensions/rtk.ts" || true)"
    if [ "$registered" -eq 0 ]; then
      run pi install "$rtk_pi_file"
      echo "  Pi: RTK extension registered"
    fi
  fi
}

configure_reasonix_step() {
  if ! have reasonix; then
    echo "  Reasonix not installed — skipping"
    return 0
  fi

  run mkdir -p "$REASONIX_SKILLS_DIR"
  configure_reasonix_mcp

  if [ ! -f "$REASONIX_SKILLS_DIR/caveman.md" ]; then
    if [ "${DRY_RUN:-0}" -eq 1 ]; then
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
