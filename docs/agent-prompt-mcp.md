# Optional Local Prompt MCP

The prompt library remains available as an explicit local utility. It is not a
managed MCP server and is no longer distributed into Claude, Codex, OpenCode,
Pi, Reasonix, or Antigravity configurations.

## Install

```bash
make prompt-sync
make agent-tools
```

`make prompt-sync` clones or updates prompt sources and writes
`~/.agent/prompts/index.json`. `make agent-tools` installs the local CLI:

- `~/.local/bin/agent-prompt`

Run the stdio adapter directly only when a local experiment needs it:

```bash
make prompt-mcp
```

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
scripts/agent-doctor.sh
```

`scripts/agent-doctor.sh` should show:

```text
--- Prompt Library ---
  OK   agent-prompt helper
  OK   prompt index: <n> records
```

AgentShield scans the explicit `~/.claude` runtime target. The private parent
may acknowledge a reviewed set in `private/agent/agentshield.baseline.json`;
the baseline stores rule/file/severity plus a hash of evidence, never raw
evidence. A rule, file, severity, or evidence-fingerprint change warns again.
Only update the baseline after human review: acknowledgement records ownership
of a known finding and is not a trust endorsement. Findings and scanner errors
do not prevent later configuration health checks from running.

## Troubleshooting

- Missing index: rerun `make prompt-sync`.
- Old prompt results: rerun `make prompt-index` after updating upstream repos.
- A host does not show the prompt server by design; invoke `make prompt-mcp`
  explicitly for a local stdio experiment.

## Source Of Truth

Markdown upstreams remain canonical. `~/.agent/prompts/index.json` is a
generated lookup contract. SQLite or vector indexes may be added later only as
generated caches, never as the canonical prompt store.
