# ADR 0002: Agent Prompt Library

**Status**: Accepted  
**Date**: 2026-06-24  

## Context

The agent setup already has a durable skill distribution model:

- canonical configuration lives under `template/agent/`
- upstream material is cloned into `~/.agent/upstream/`
- generated shared state lives under `~/.agent/`
- agent-specific directories are consumer views

Prompt collections such as Fabric patterns and Wonderful Prompts are useful to
reuse in Codex, Claude, OpenCode, and MCP-capable agents. Copying prompt text by
hand is slow and loses provenance. Vendoring entire prompt repos into
`template/` would bloat the public template and make upstream updates harder to
audit.

## Decision

Create an agent prompt library beside the skill system:

- `template/agent/prompts/sources.json` is the source registry.
- `template/scripts/sync-agent-prompts.sh` clones or fast-forwards prompt repos
  under `~/.agent/upstream/`.
- `template/scripts/agent-prompt-index.py` builds `~/.agent/prompts/index.json`
  from local upstream markdown.
- `template/scripts/agent-prompt.sh` provides list/search/show lookup for
  agents and shell use.
- `template/scripts/agent-prompt-mcp.sh` runs a stdio MCP server implementing
  the official MCP prompts capability over the same generated index, negotiating
  the current protocol version while keeping compatibility with 2025-06-18
  clients.
- `make prompt-sync`, `make prompt-index`, and `make prompt-list` expose the
  workflow.
- `make agent-sync` syncs skills and prompt libraries; `make skill-refresh`
  remains skill-only.

The initial sources are:

- `danielmiessler/fabric` using `data/patterns/*/{system.md,user.md}`
- `langgptai/wonderful-prompts` using markdown heading sections

## Rationale

Markdown remains the canonical content format because both upstream repos are
already maintained that way and Fabric documents markdown-based patterns as its
own prompt format.

JSON index is the right first lookup layer:

- no runtime database dependency for Codex or shell usage
- easy to diff, inspect, test, and regenerate
- enough metadata for source, license, file path, and line range
- suitable input for the prompt-library MCP server

SQLite should be a generated cache, not the source of truth. If MCP search later
needs FTS ranking or usage telemetry, generate SQLite from the same markdown and
`index.json` so the data model does not fork.

## Consequences

Positive:

- prompts become discoverable through one command instead of manual copy/paste
- upstream provenance and licenses stay attached to records
- MCP integration stays thin and reads the existing index
- public template remains small and privacy-safe

Tradeoffs:

- first sync needs network and disk for upstream repos
- markdown-section extraction is heuristic for large README-style collections
- generated index must be rebuilt after upstream changes

## Verification

- `make prompt-sync` clones or updates sources and builds the prompt index.
- `agent-prompt list <query>` returns matching prompt IDs.
- `agent-prompt show <id>` prints prompt content on demand.
- `agent-prompt-mcp` answers `initialize`, `prompts/list`, `prompts/get`,
  `tools/list`, and `tools/call` over newline-delimited JSON-RPC stdio.
- `make doctor-agent` reports helper and index status.
- pytest covers registry shape, Makefile targets, venv Python usage, and a
  synthetic end-to-end index/show flow.

References:

- https://modelcontextprotocol.io/specification/latest/basic/lifecycle
- https://modelcontextprotocol.io/specification/latest/basic/transports
- https://modelcontextprotocol.io/specification/latest/server/prompts
