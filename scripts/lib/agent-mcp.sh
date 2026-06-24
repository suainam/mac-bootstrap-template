#!/usr/bin/env bash

write_json_file() {
  local path="$1" code="$2"
  run mkdir -p "$(dirname "$path")"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
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
      ALL_PROXY: process.env.ALL_PROXY || proxy,
    };
  }
  return cfg;
};

const getPromptLibraryConfig = () => ({
  command: process.env.HOME + "/.local/bin/agent-prompt-mcp",
  args: [],
});

const fn = new Function("fs", "path", "key", "getContext7Config", "getPromptLibraryConfig", code);
fn(fs, path, key, getContext7Config, getPromptLibraryConfig);
NODE
  fi
}

ensure_code_review_graph() {
  if have code-review-graph; then
    return 0
  fi
  if have uv; then
    run uv tool install code-review-graph
  else
    echo "  SKIP: uv not installed — cannot install code-review-graph"
  fi
}

configure_claude_mcp() {
  [ -f "$CLAUDE_MCP_JSON" ] || return 0
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
cfg.mcpServers["agent-prompt-library"] = getPromptLibraryConfig();
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Claude Code: CRG + context7 + prompt-library MCP configured"
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
    "$python_bin" "$BOOTSTRAP/scripts/render-codex-mcp-block.py" \
      "${render_args[@]}" > "$tmp_block"
    "$python_bin" "$BOOTSTRAP/scripts/sync-codex-mcp-config.py" "$CODEX_TOML" "$tmp_block"
    rm -f "$tmp_block"
  fi
  echo "  Codex: context-mode + CRG + context7 + prompt-library MCP configured"
}

configure_opencode_mcp() {
  [ -f "$OPENCODE_CONFIG" ] || return 0
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
const prompt = getPromptLibraryConfig();
cfg.mcp["agent-prompt-library"] = { enabled: true, type: "local", command: [prompt.command].concat(prompt.args) };
fs.writeFileSync(path, JSON.stringify(cfg, null, 4) + "\n");
'
  echo "  OpenCode: CRG + context7 + prompt-library MCP configured"
}

configure_pi_mcp_file() {
  write_json_file "$PI_MCP_JSON" '
const cfg = {
  mcpServers: {
    "code-review-graph": { command: "code-review-graph", args: ["serve"] },
    "context7": getContext7Config(key),
    "agent-prompt-library": getPromptLibraryConfig()
  }
};
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Pi: mcp.json updated with CRG + context7 + prompt-library"
}

configure_reasonix_mcp() {
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
cfg.mcpServers["agent-prompt-library"] = getPromptLibraryConfig();
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Reasonix: config.json merged with CRG + context7 + prompt-library MCP"
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
  write_json_file "$ANTIGRAVITY_MCP_JSON" '
const cfg = {
  mcpServers: {
    "code-review-graph": { command: "code-review-graph", args: ["serve"] },
    "context7": getContext7Config(key),
    "agent-prompt-library": getPromptLibraryConfig()
  }
};
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Antigravity: mcp_config.json updated with CRG + context7 + prompt-library"
}

configure_all_mcp() {
  configure_claude_mcp
  configure_codex_mcp
  configure_opencode_mcp
}
