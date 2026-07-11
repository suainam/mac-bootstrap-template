# Agent Prompt MCP

`agent-prompt-library` exposes the local Fabric and Wonderful Prompts index as
an MCP stdio server. It lets Codex and other MCP-capable agents discover stored
prompt templates without manual copy and paste.

## Install

```bash
make prompt-sync
make agent-tools
```

`make prompt-sync` clones or updates prompt sources and writes
`~/.agent/prompts/index.json`. `make agent-tools` installs:

- `~/.local/bin/agent-prompt`
- `~/.local/bin/agent-prompt-mcp`

Codex MCP config is generated with an absolute command path:

```toml
[mcp_servers.agent-prompt-library]
enabled = false
command = "<home>/.local/bin/agent-prompt-mcp"
args = []

[mcp_servers.agent-prompt-library.tools.search_prompts]
approval_mode = "approve"
```

Codex keeps this optional server disabled in normal sessions. Start an on-demand
session with `codex-mcp prompts`; other supported agents continue using their
host-specific generated MCP configuration.

## CLI Use

```bash
agent-prompt list wisdom
agent-prompt show fabric:extract_wisdom
agent-prompt doctor
```

Prompt IDs are stable `<source>:<name>` values such as:

- `fabric:extract_wisdom`
- `wonderful-prompts:prompt-生成优化`

## MCP Contract

The server implements the official MCP prompts capability using stdio transport.
Context7 was used to verify the current MCP specification on 2026-06-24:

- `initialize` negotiates protocol versions and returns server capabilities.
- The server advertises `prompts` and a read-only `tools` capability.
- `prompts/list` returns prompt definitions and supports `cursor` pagination.
- `prompts/get` returns prompt messages with text content.
- stdio messages are newline-delimited JSON-RPC over stdin/stdout.
- stderr is reserved for logs if needed; normal server output stays JSON-RPC.

The implementation prefers protocol `2025-11-25` and keeps compatibility with
`2025-06-18` clients.

## JSON-RPC Smoke

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"prompts/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"prompts/get","params":{"name":"fabric:extract_wisdom","arguments":{"input":"meeting notes"}}}' \
  | agent-prompt-mcp
```

Expected checks:

- response `id=1` includes `protocolVersion: "2025-11-25"`
- response `id=1` includes `capabilities.prompts`
- response `id=2` includes prompt records
- response `id=3` includes `messages[0].content.type: "text"`

## Agent Verification

```bash
codex mcp get agent-prompt-library
codex-mcp prompts mcp get agent-prompt-library
scripts/agent-doctor.sh
```

`scripts/agent-doctor.sh` should show:

```text
--- Prompt Library ---
  OK   agent-prompt helper
  OK   agent-prompt-mcp helper
  OK   prompt index: <n> records
```

AgentShield findings are reported as warnings so they do not prevent later
configuration health checks from running.

## Troubleshooting

- Missing `agent-prompt-mcp`: rerun `make agent-tools`.
- Missing index: rerun `make prompt-sync`.
- Old prompt results: rerun `make prompt-index` after updating upstream repos.
- Codex does not show the server definition: run `make agent-tools`.
- Codex shows the server as disabled: use `codex-mcp prompts` for that session.
- MCP client cannot start the server: verify that the generated config uses the
  absolute `~/.local/bin/agent-prompt-mcp` target and that the symlink exists.

## Source Of Truth

Markdown upstreams remain canonical. `~/.agent/prompts/index.json` is a
generated lookup contract. SQLite or vector indexes may be added later only as
generated caches, never as the canonical prompt store.
