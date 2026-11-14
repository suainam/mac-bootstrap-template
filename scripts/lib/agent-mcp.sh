#!/usr/bin/env bash

write_json_file() {
  local target_path="$1" code="$2"
  run mkdir -p "$(dirname "$target_path")"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: write JSON config $target_path"
  else
    node - "$target_path" "$code" <<'NODE'
const fs = require("fs");
const path = process.argv[2];
const code = process.argv[3];
const fn = new Function("fs", "path", code);
fn(fs, path);
NODE
  fi
}

write_mcp_config() {
  local host="$1" target_path="$2" context7_command="npx"
  local python_bin="${PYTHON:-$BOOTSTRAP/.venv/bin/python}"
  if have context7-mcp; then
    context7_command="$(command -v context7-mcp)"
  fi
  run mkdir -p "$(dirname "$target_path")"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: render $host MCP config $target_path"
    return 0
  fi
  "$python_bin" "$BOOTSTRAP/scripts/agent_mcp_runtime.py" render-json \
    --host "$host" \
    --path "$target_path" \
    --bootstrap "$BOOTSTRAP" \
    --context7-command "$context7_command"
}

ensure_codebase_memory_mcp() {
  if have codebase-memory-mcp; then
    return 0
  fi
  if have npm; then
    run npm install -g codebase-memory-mcp
  else
    echo "  SKIP: npm not installed — cannot install codebase-memory-mcp"
  fi
}

configure_claude_mcp() {
  [ -f "$CLAUDE_MCP_JSON" ] || return 0
  write_mcp_config claude "$CLAUDE_MCP_JSON"
  echo "  Claude Code: CBM + context7 MCP configured"
}

configure_codex_mcp() {
  [ -f "$CODEX_TOML" ] || return 0

  local ctx7_cmd_path
  if have context7-mcp; then
    ctx7_cmd_path="$(command -v context7-mcp)"
  else
    ctx7_cmd_path="npx"
  fi

  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: rewrite managed MCP stanzas in $CODEX_TOML"
  else
    local tmp_block
    local python_bin="${PYTHON:-$BOOTSTRAP/.venv/bin/python}"
    tmp_block="$(mktemp)"
    local render_args=(--context7-command "$ctx7_cmd_path")
    "$python_bin" "$BOOTSTRAP/scripts/render-codex-mcp-block.py" \
      "${render_args[@]}" > "$tmp_block"
    "$python_bin" "$BOOTSTRAP/scripts/sync-codex-mcp-config.py" "$CODEX_TOML" "$tmp_block"
    rm -f "$tmp_block"

    rm -f "$(dirname "$CODEX_TOML")"/{docs,prompts,full}.config.toml
    run ln -sfn "$BOOTSTRAP/scripts/codex-mcp-profile.py" "$HOME/.local/bin/codex-mcp"
  fi
  echo "  Codex: core MCPs + on-demand profiles configured"
}

configure_opencode_mcp() {
  [ -f "$OPENCODE_CONFIG" ] || return 0
  write_mcp_config opencode "$OPENCODE_CONFIG"
  echo "  OpenCode: CBM + context7 MCP configured"
}


configure_reasonix_mcp() {
  write_mcp_config reasonix "$REASONIX_CONFIG"
  echo "  Reasonix: config.json merged with CBM + context7 MCP"
}

configure_antigravity_settings_file() {
  local template_settings="${BOOTSTRAP}/agent/agy/settings.json"
  local private_dir="${MAC_BOOTSTRAP_PRIVATE_DIR:-}"
  if [ -z "$private_dir" ] && [ -d "${BOOTSTRAP}/../private" ]; then
    private_dir="$(cd "${BOOTSTRAP}/../private" && pwd)"
  fi
  local private_settings="${private_dir:+$private_dir/agent/agy/settings.json}"

  AGY_TEMPLATE_SETTINGS="$template_settings" \
  AGY_PRIVATE_SETTINGS="$private_settings" \
  write_json_file "$ANTIGRAVITY_SETTINGS" '
const readJson = (p) => {
  if (!p || !fs.existsSync(p)) return null;
  const raw = fs.readFileSync(p, "utf8").trim();
  return raw ? JSON.parse(raw) : {};
};
const uniq = (arr) => Array.from(new Set(arr));

let cfg = readJson(path) || {};
const tmpl = readJson(process.env.AGY_TEMPLATE_SETTINGS);
const priv = readJson(process.env.AGY_PRIVATE_SETTINGS);

const mergeLayer = (layer) => {
  if (!layer || typeof layer !== "object") return;
  for (const [k, v] of Object.entries(layer)) {
    if (k === "permissions" && v && typeof v === "object") {
      cfg.permissions = cfg.permissions && typeof cfg.permissions === "object" ? cfg.permissions : {};
      for (const listKey of ["allow", "ask", "deny"]) {
        if (Array.isArray(v[listKey])) {
          const prev = Array.isArray(cfg.permissions[listKey]) ? cfg.permissions[listKey] : [];
          cfg.permissions[listKey] = uniq([...prev, ...v[listKey]]);
        }
      }
    } else if (k === "trustedWorkspaces" && Array.isArray(v)) {
      const prev = Array.isArray(cfg.trustedWorkspaces) ? cfg.trustedWorkspaces : [];
      cfg.trustedWorkspaces = uniq([...prev, ...v]);
    } else if (k === "skills" && Array.isArray(v)) {
      const prev = Array.isArray(cfg.skills) ? cfg.skills : [];
      cfg.skills = uniq([...prev, ...v]);
    } else {
      cfg[k] = v;
    }
  }
};

mergeLayer(tmpl);
mergeLayer(priv);

cfg.skills = Array.isArray(cfg.skills) ? cfg.skills : [];
const skillsPath = process.env.HOME + "/.gemini/antigravity-cli/skills";
if (!cfg.skills.includes(skillsPath)) cfg.skills.push(skillsPath);
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Antigravity: settings.json updated"
}

configure_antigravity_mcp_file() {
  write_mcp_config antigravity "$ANTIGRAVITY_MCP_JSON"
  echo "  Antigravity: mcp_config.json updated with CBM + context7"
}

configure_all_mcp() {
  configure_claude_mcp
  configure_codex_mcp
  configure_opencode_mcp
}
