#!/usr/bin/env bash

write_json_file() {
  local target_path="$1" code="$2"
  run mkdir -p "$(dirname "$target_path")"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: write JSON config $target_path"
  else
    node - "$target_path" "$CONTEXT7_KEY" "$BOOTSTRAP" "$code" <<'NODE'
const fs = require("fs");
const { execSync } = require("child_process");
const path = process.argv[2];
const key = process.argv[3] || "";
const bootstrap = process.argv[4] || "";
const code = process.argv[5];

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

const getXDocsConfig = () => ({
  url: "https://docs.x.com/mcp",
});

const getDevSpaceConfig = () => {
  const enabled = process.env.DEVSPACE_MCP_ENABLE === "1";
  const url = process.env.DEVSPACE_MCP_URL || "";
  if (!enabled || !url) return null;
  return { url };
};

const getXApiConfig = () => {
  const enabled = process.env.X_MCP_ENABLE === "1";
  if (!enabled) {
    return null;
  }
  return {
    command: bootstrap + "/scripts/x-mcp-bridge.sh",
    args: [],
    startup_timeout_sec: 300,
  };
};

const fn = new Function("fs", "path", "key", "getContext7Config", "getPromptLibraryConfig", "getXDocsConfig", "getDevSpaceConfig", "getXApiConfig", code);
fn(fs, path, key, getContext7Config, getPromptLibraryConfig, getXDocsConfig, getDevSpaceConfig, getXApiConfig);
NODE
  fi
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
  write_json_file "$CLAUDE_MCP_JSON" '
let cfg = {};
if (fs.existsSync(path)) {
  const raw = fs.readFileSync(path, "utf8").trim();
  if (raw) cfg = JSON.parse(raw);
}
if (!cfg.mcpServers) cfg.mcpServers = {};
delete cfg.mcpServers["code-review-graph"];
cfg.mcpServers["codebase-memory-mcp"] = { command: "codebase-memory-mcp", args: [] };
cfg.mcpServers["context7"] = getContext7Config(key);
cfg.mcpServers["agent-prompt-library"] = getPromptLibraryConfig();
cfg.mcpServers["x-docs"] = getXDocsConfig();
const devspace = getDevSpaceConfig();
if (devspace) cfg.mcpServers["devspace"] = devspace;
else delete cfg.mcpServers["devspace"];
const xapi = getXApiConfig();
if (xapi) cfg.mcpServers["xapi"] = xapi;
else delete cfg.mcpServers["xapi"];
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
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
  write_json_file "$OPENCODE_CONFIG" '
let cfg = {};
if (fs.existsSync(path)) {
  const raw = fs.readFileSync(path, "utf8").trim();
  if (raw) cfg = JSON.parse(raw);
}
if (!cfg.mcp) cfg.mcp = {};
delete cfg.mcp["code-review-graph"];
cfg.mcp["codebase-memory-mcp"] = { enabled: true, type: "local", command: ["codebase-memory-mcp"] };
const c7 = getContext7Config(key);
cfg.mcp["context7"] = { enabled: true, type: "local", command: [c7.command].concat(c7.args) };
if (c7.env) cfg.mcp["context7"].env = c7.env;
const prompt = getPromptLibraryConfig();
cfg.mcp["agent-prompt-library"] = { enabled: true, type: "local", command: [prompt.command].concat(prompt.args) };
cfg.mcp["x-docs"] = { enabled: true, type: "remote", url: getXDocsConfig().url };
const devspace = getDevSpaceConfig();
if (devspace) cfg.mcp["devspace"] = { enabled: true, type: "remote", url: devspace.url };
else delete cfg.mcp["devspace"];
const xapi = getXApiConfig();
if (xapi) {
  cfg.mcp["xapi"] = { enabled: true, type: "local", command: [xapi.command].concat(xapi.args) };
  if (xapi.env) cfg.mcp["xapi"].env = xapi.env;
} else {
  delete cfg.mcp["xapi"];
}
fs.writeFileSync(path, JSON.stringify(cfg, null, 4) + "\n");
'
  echo "  OpenCode: CBM + context7 + prompt-library + X docs MCP configured"
}

configure_pi_mcp_file() {
  write_json_file "$PI_MCP_JSON" '
const cfg = {
  mcpServers: {
    "codebase-memory-mcp": { command: "codebase-memory-mcp", args: [] },
    "context7": getContext7Config(key),
    "agent-prompt-library": getPromptLibraryConfig(),
    "x-docs": getXDocsConfig()
  }
};
const devspace = getDevSpaceConfig();
if (devspace) cfg.mcpServers["devspace"] = devspace;
const xapi = getXApiConfig();
if (xapi) cfg.mcpServers["xapi"] = xapi;
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Pi: mcp.json updated with CBM + context7 + prompt-library + X docs"
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
delete cfg.mcpServers["code-review-graph"];
delete cfg.mcpServers["codebase-memory"];
cfg.mcpServers["codebase-memory-mcp"] = { command: "codebase-memory-mcp", args: [] };
cfg.mcpServers["context7"] = getContext7Config(key);
cfg.mcpServers["agent-prompt-library"] = getPromptLibraryConfig();
cfg.mcpServers["x-docs"] = getXDocsConfig();
const devspace = getDevSpaceConfig();
if (devspace) cfg.mcpServers["devspace"] = devspace;
else delete cfg.mcpServers["devspace"];
const xapi = getXApiConfig();
if (xapi) cfg.mcpServers["xapi"] = xapi;
else delete cfg.mcpServers["xapi"];
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
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
  write_json_file "$ANTIGRAVITY_MCP_JSON" '
const cfg = {
  mcpServers: {
    "codebase-memory-mcp": { command: "codebase-memory-mcp", args: [] },
    "context7": getContext7Config(key),
    "agent-prompt-library": getPromptLibraryConfig(),
    "x-docs": getXDocsConfig()
  }
};
const devspace = getDevSpaceConfig();
if (devspace) cfg.mcpServers["devspace"] = devspace;
const xapi = getXApiConfig();
if (xapi) cfg.mcpServers["xapi"] = xapi;
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n");
'
  echo "  Antigravity: mcp_config.json updated with CBM + context7 + prompt-library + X docs"
}

configure_all_mcp() {
  configure_claude_mcp
  configure_codex_mcp
  configure_opencode_mcp
}
