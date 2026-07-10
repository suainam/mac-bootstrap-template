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
  echo "  Claude Code: CBM + context7 + prompt-library + X docs MCP configured"
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
    if [ -n "${CONTEXT7_KEY:-}" ]; then
      render_args+=(--context7-api-key "$CONTEXT7_KEY")
    fi
    if [ "${X_MCP_ENABLE:-0}" = "1" ]; then
      render_args+=(--enable-x-api --x-api-command "$BOOTSTRAP/scripts/x-mcp-bridge.sh")
    fi
    if [ "${DEVSPACE_MCP_ENABLE:-0}" = "1" ] && [ -n "${DEVSPACE_MCP_URL:-}" ]; then
      render_args+=(--devspace-url "$DEVSPACE_MCP_URL")
    fi
    "$python_bin" "$BOOTSTRAP/scripts/render-codex-mcp-block.py" \
      "${render_args[@]}" > "$tmp_block"
    "$python_bin" "$BOOTSTRAP/scripts/sync-codex-mcp-config.py" "$CODEX_TOML" "$tmp_block"
    rm -f "$tmp_block"
  fi
  echo "  Codex: context-mode + CBM + context7 + prompt-library + X docs MCP configured"
}

configure_opencode_mcp() {
  [ -f "$OPENCODE_CONFIG" ] || return 0
  write_mcp_config opencode "$OPENCODE_CONFIG"
  echo "  OpenCode: CBM + context7 + prompt-library + X docs MCP configured"
}

configure_pi_mcp_file() {
  write_mcp_config pi "$PI_MCP_JSON"
  echo "  Pi: mcp.json updated with CBM + context7 + prompt-library + X docs"
}

configure_reasonix_mcp() {
  write_mcp_config reasonix "$REASONIX_CONFIG"
  echo "  Reasonix: config.json merged with CBM + context7 + prompt-library + X docs MCP"
}

configure_antigravity_settings_file() {
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
}

configure_antigravity_mcp_file() {
  write_mcp_config antigravity "$ANTIGRAVITY_MCP_JSON"
  echo "  Antigravity: mcp_config.json updated with CBM + context7 + prompt-library + X docs"
}

configure_all_mcp() {
  configure_claude_mcp
  configure_codex_mcp
  configure_opencode_mcp
}
