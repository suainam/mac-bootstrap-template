# Agent Prompt Library

This directory defines reusable prompt-library sources. The prompt text itself
is synced into `~/.agent/prompts/` from upstream repositories; this repo keeps
only source metadata, indexing rules, and distribution scripts.

## Why This Shape

- Markdown stays the source of truth because Fabric and Wonderful Prompts are
  already maintained as markdown files.
- `~/.agent/prompts/index.json` is the generated lookup layer for agents,
  scripts, and the prompt-library MCP server.
- SQLite is not the first source of truth. It can be added later as a cache for
  MCP search/ranking, generated from the same JSON index and upstream markdown.
- Upstream repos are cloned under `~/.agent/upstream/`, matching the existing
  skill-sync model and avoiding large vendored prompt content in `template/`.

## Commands

```bash
make prompt-sync
make prompt-index
make prompt-mcp
template/scripts/agent-prompt.sh list analyze
template/scripts/agent-prompt.sh show fabric:extract_wisdom
```

`make agent-sync` also syncs prompt sources.

## Runtime Layout

```text
~/.agent/
  upstream/
    fabric/
    wonderful-prompts/
  prompts/
    index.json
```

## Source Contract

Add prompt libraries in `sources.json` with:

- `repo`: Git URL.
- `upstream_dir`: directory under `~/.agent/upstream/`.
- `mode`: currently `fabric-patterns` or `markdown-sections`.
- `license`: license label to preserve in generated metadata.
- source-specific fields such as `patterns_path` or `files`.

The generated index stores IDs, titles, source file paths, line ranges, and
license metadata. Agents should load prompt content on demand through
`agent-prompt.sh show <id>` instead of copying large prompt bodies into global
instructions.

## MCP Path

`scripts/agent-prompt-mcp.sh` runs a stdio MCP server backed by the generated
index. It follows the official MCP prompts capability and negotiates the
current protocol version while keeping compatibility with 2025-06-18 clients:

- `initialize` advertises `prompts` and `tools` capabilities.
- `prompts/list` returns indexed prompt templates.
- `prompts/get` returns MCP prompt messages for one stored prompt.
- `tools/list` exposes a read-only `search_prompts` helper.
- `tools/call` runs `search_prompts` for discovery before selecting a prompt.

Reference:

- https://modelcontextprotocol.io/specification/latest/server/prompts
- https://modelcontextprotocol.io/specification/latest/basic/lifecycle
- https://modelcontextprotocol.io/specification/latest/basic/transports

Usage guide:

- ../../docs/agent-prompt-mcp.md

Do not make SQLite or a vector store the canonical prompt store. Generate those
indexes from markdown and JSON when needed.
