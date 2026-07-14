# Agent Tooling — Architecture & Usage Guide

Skill source lineage, local sources, quarantine, and distribution operations live
under [`../agent-skills/`](../agent-skills/README.md). This directory owns agent
runtime configuration only.

## One-Command Setup

```bash
# From bootstrap repo root:
make bootstrap   # Brewfile deps + shell/vim/neovim/tmux config
make agent-sync  # Validate/distribute registry-enabled skills + sync prompt libraries
make agent-tools # Configure RTK, caveman, CBM, context7 + wire skills for all agents
make agent-refresh # Full sync + full agent reconfigure
make skill-refresh # Validate and distribute landed registry sources only
make prompt-sync # Sync Fabric/Wonderful prompt libraries + rebuild index
make prompt-mcp  # Run prompt-library MCP stdio server
make doctor-agent # Verify all configs
make security-scan  # AgentShield security audit
```

Agent paths and targets are driven from
[`agent-manifest.json`](agent-manifest.json); Codex MCP startup defaults and
profiles are driven from [`mcp-policy.json`](mcp-policy.json). Edit canonical
sources once, then re-run `make agent-tools`.
Generated runtime markdown files are intentionally short and ordered:
`12-rules` first, then `RTK`, then `CBM / docs`.

### Codex MCP Profiles

Codex MCP startup policy is managed in [`mcp-policy.json`](mcp-policy.json).
Keep server connection definitions in `scripts/agent_mcp_runtime.py`; use the
policy file only for default enablement and named profiles. Run `make
agent-tools` after changing either source.

The base Codex session starts core MCPs plus Context7. Other optional MCPs are
enabled per session through generated profiles:

```bash
codex-mcp docs       # context7 profile override
codex-mcp prompts    # agent-prompt-library
codex-mcp devspace   # authenticated remote DevSpace
codex-mcp full       # all optional managed MCPs
```

The generated `~/.local/bin/codex-mcp` launcher converts the selected profile
into per-session Codex config overrides. Profiles control Codex only because
other supported hosts do not share one portable profile contract.

Codex Context7 launches through `scripts/context7-mcp-bridge.py`. Agent refresh
and doctor validate the optional key in `private/agent/context7.runtime.jsonc`
and restore mode `0600` before reading it; the wrapper passes the key only to
the child environment at process start.
Generated configs and non-Codex hosts remain keyless; a missing key uses the
anonymous Context7 service. Check the private file mode with
`stat -f '%Sp' private/agent/context7.runtime.jsonc` (expect `-rw-------`) and
managed state with `make doctor-agent`; refresh with `make agent-tools`.

---

## Architecture

### Canonical Sources

```
agent/agent-manifest.json             ← Agent locations + config targets (edit here)
agent/rules/12-rules.md               ← Canonical instruction source
  → ~/.claude/12-rules.md            ← Symlink (Claude @include reads it)
  → ~/.codex/AGENTS.md @/path/ref    ← Codex reads via @/path/to/file
  → ~/.pi/agent/AGENTS.md @~/.claude/12-rules.md  ← Pi reads via AGENTS.md ref
  → ~/.claude/CLAUDE.md @12-rules.md              ← Reasonix inherits via Claude docs
  → ~/.claude/CLAUDE.md @RTK.md                   ← RTK follows 12-rules

agent/rules/common/                   ← Canonical rules dir
  → ~/.claude/rules/common/          ← Claude Code auto-loads rules

agent/rules/python/                   ← Canonical python rules
  → ~/.claude/rules/python/          ← Claude Code auto-loads rules

~/work/GEMINI.md                      ← Generated workspace rules for Antigravity
~/work/REASONIX.md                    ← Generated workspace rules for Reasonix
~/.pi/agent/AGENTS.md                 ← Generated global rules for Pi
```

### Install Scripts (Write Agent Configs)

`scripts/install-agent-tooling.sh --configure` reads the manifest and is the
single distribution entrypoint for:
- OpenCode `AGENTS.md` (embeds 12-rules from canonical file)
- Codex `hooks.json` (adds caveman hooks + context-mode)
- Quality gate policy under `template/agent/quality-gates/manifest.jsonc`
- Caveman default mode (`~/.config/caveman/config.json`)
- Pi `settings.json` + `mcp.json` + AGENTS.md ref
- Reasonix config.json + skills
- Antigravity `settings.json` + `mcp_config.json` + skills
- Workspace `GEMINI.md` + `REASONIX.md` generated from canonical rules
- OpenCode plugin list (rtk, caveman, context-mode)
- MCP profiles (`~/.zshrc`)
- Hook matchers (console.log guards, destructive op warnings)
- Skill setup delegates to the registry-driven distributor documented in
  [`../agent-skills/README.md`](../agent-skills/README.md).

The script is intentionally split by responsibility:

- `scripts/install-agent-tooling.sh` — thin step runner / orchestration only

## Agent Quality Gates

- Policy source: `template/agent/quality-gates/manifest.jsonc`
- Runner source: `template/scripts/agent-quality-gate.sh`
- Repo-managed git hooks are authoritative for real `commit` / `push` events.
- Codex `hooks.json` does not own quality gate execution and should not guess git intent from prompts.
- Codex hook commands use `hooks.json` only; `config.toml` must not define a second hook representation.
- `pre-commit` is fast and path-sensitive.
- `pre-push` is authoritative and runs doc alignment, repo validation, and knowledge recording.
- `QUALITY_GATES_BYPASS=1` is break-glass only and is reported by doctor output.
- `scripts/lib/agent-shared.sh` — shell helpers (run/try_run, managed block writes)
- `scripts/lib/agent-manifest.sh` — manifest/path resolution
- `scripts/agent_mcp_runtime.py` — normalized MCP desired state, host adapters, rendering, and semantic audit
- `scripts/lib/agent-mcp.sh` — thin shell adapters that apply normalized MCP state
- `scripts/lib/agent-configure.sh` — per-step agent/platform configuration bodies
- `scripts/sync-agent-prompts.sh` + `scripts/agent-prompt-index.py` — prompt-library sync/index
- `scripts/render-codex-mcp-block.py` + `scripts/sync-codex-mcp-config.py` — compatibility CLI and idempotent Codex managed-section rewrite
- `scripts/run-doctor-checks.py` + `scripts/doctor-manifest.json` — data-driven doctor checks derived from Brewfile

MCP reconciliation preserves unrelated root keys and unmanaged servers. It removes
retired graph-server aliases and initializes `reasonix.skipSetup` only when absent.
Context7 proxy values are treated as volatile during doctor comparison.
Remote OAuth authorization is runtime readiness, not desired-state drift.

---

## Agent Config Matrix

| Tool | Claude Code | Codex CLI | OpenCode | Pi | Reasonix | Antigravity |
|------|:-----------:|:---------:|:--------:|:--:|:--------:|:------------:|
| **RTK** | ✅ hook+RTK.md | ✅ RTK.md+AGENTS.md | ✅ plugin | ✅ extension + settings.json | ❌ | ❌ |
| **Caveman** | ✅ plugin+ultra | ✅ skills+hooks | ✅ plugin+ultra | ✅ skill file | ✅ skill file |
| **Context-mode** | ✅ plugin | ✅ hooks | ✅ plugin | ❌ | ❌ | ❌ |
| **CBM** | ✅ MCP | ✅ MCP in config.toml | ✅ MCP | ✅ `mcp.json` | ✅ MCP server | ✅ `mcp_config.json` |
| **12 Rules** | ✅ @12-rules.md | ✅ @/path ref | ✅ inline embedded | ✅ inline AGENTS.md | ✅ workspace `REASONIX.md` | ✅ workspace/global `GEMINI.md` |
---

## Skill Supply Chain Boundary

Skill source lineage, taxonomy, quarantine, validation, and distribution are
owned outside this runtime directory. See
[`../agent-skills/README.md`](../agent-skills/README.md) for the source-tree
contract and [`../docs/skill-supply-chain.md`](../docs/skill-supply-chain.md)
for operations.

---

## Prompt Libraries

Prompt libraries are managed like upstream skills, but they are lookup material
instead of auto-loaded global instructions.

```bash
make prompt-sync                 # clone/update Fabric + Wonderful Prompts and rebuild index
make prompt-index                # rebuild ~/.agent/prompts/index.json from local upstreams
make prompt-list Q=analyze       # list matching prompt records
make prompt-mcp                  # run MCP stdio server
agent-prompt show fabric:extract_wisdom
```

Source registry:

- `agent/prompts/sources.json` — canonical prompt-library source list
- `~/.agent/upstream/fabric` — Fabric repo clone
- `~/.agent/upstream/wonderful-prompts` — Wonderful Prompts repo clone
- `~/.agent/prompts/index.json` — generated lookup index

Decision rule:

- Keep markdown upstreams as source of truth.
- Keep `index.json` as the agent/MCP lookup contract.
- Add SQLite later only as a generated FTS/cache layer, not as canonical data.

`agent-prompt-mcp` reads `agent/prompts/sources.json` and
`~/.agent/prompts/index.json`, then loads content by source file and line range
or Fabric pattern directory on demand. See
[`docs/agent-prompt-mcp.md`](../docs/agent-prompt-mcp.md) for the MCP contract,
Codex config shape, smoke test, and troubleshooting steps.

---

## Adding a New MCP Server

Managed MCP servers are declared once in `scripts/agent_mcp_runtime.py` as a
`ServerSpec`. Set `hosts` explicitly, add host-adapter and audit tests, then run:

```bash
make agent-tools
make doctor-agent
```

Do not hand-edit a managed server in `~/.codex/config.toml`,
`~/.claude/.mcp.json`, or another generated consumer view. Reconciliation will
restore desired state. One-off servers with names outside the managed and
retired catalogs are preserved as unmanaged configuration.

Plugin-owned MCP servers remain plugin-owned; do not copy them into this
catalog unless mac-bootstrap is intentionally taking ownership.

### Legacy ECC MCP Exclusions

`ECC_DISABLED_MCPS` belongs to the inherited ECC setup and does not control the
managed Codex catalog above. Set it only for ECC-owned MCPs:

```bash
export ECC_DISABLED_MCPS="caveman-shrink,memory"
```

Or permanently in `~/.zshrc` (already configured by `make agent-tools`).

---

## ECC Features Borrowed

| # | Feature | How to Use |
|---|---------|------------|
| 1 | **AgentShield** | `make security-scan` — runs `npx ecc-agentshield scan --fix` |
| 2 | **Instincts** | `~/.agent/instincts/active/` — session learnings with confidence scores |
| 3 | **Language Rules** | `~/.claude/rules/{common,python}/` — auto-loaded by Claude Code |
| 4 | **ECC MCP Exclusions** | `export ECC_DISABLED_MCPS="server1,server2"` |
| 5 | **PM Detection** | `make pm-detect` — 6-level priority chain |
| 6 | **Hook Matchers** | PreToolUse guards for console.log/destructive ops |
| 7 | **Eval Loop** | Retained under `agent-skills/local/deprecated/eval-loop/SKILL.md` |

---

## Package Manager Detection

The `scripts/detect-package-manager.sh` script detects the best package manager
for the current project using this priority chain:

1. `CLAUDE_PACKAGE_MANAGER` env var
2. `.claude/package-manager.json` project config
3. `package.json` → `packageManager` field
4. Lock file presence (`pnpm-lock.yaml` → pnpm, etc.)
5. `~/.claude/package-manager.json` global config
6. First available: pnpm > yarn > bun > npm

```bash
make pm-detect          # Auto-detect
make pm-set PNPM        # Set global default
```

---

## Reasonix (DeepSeek Agent)

**Status**: Installed (`/opt/homebrew/bin/reasonix` v0.53.2). Configured with
CBM + context7 MCP and caveman skill. Rules come from `~/.claude/CLAUDE.md`.

Reasonix uses:
- Config: `~/.reasonix/config.json` — includes `mcpServers`
- Skills: `~/.reasonix/skills/` (global) or `<project>/.reasonix/skills/` (project)
- MCP: in config.json under `mcpServers`
- Hooks: `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`
- First-time setup: Run `reasonix setup` to configure API key and provider.
  Then skills and MCP are pre-configured by `make agent-tools`.

---

## Pi Terminal Agent

**Status**: Installed (`/opt/homebrew/bin/pi` v0.77.0). RTK extension registered,
`pi-mcp-extension` installed, local OpenAI-compatible provider wired, CBM +
context7 configured as MCP servers, skills installed, AGENTS.md wired.

Pi uses:
- Config: `~/.pi/agent/settings.json` (global), `.pi/settings.json` (project)
- MCP: `~/.pi/agent/mcp.json` (global), `.pi/mcp.json` (project)
- Extensions: TypeScript modules under `~/.pi/agent/extensions/`
- Skills: directory skills in `~/.pi/agent/skills/`
- Prompt templates: `~/.pi/agent/prompts/`
- Packages: Bundle extensions/skills into `.pi-pack` files

**Important**: Extensions must be registered with `pi install` (not just copied).
The install script runs `pi install ~/.pi/agent/extensions/rtk.ts` and
`pi install npm:pi-mcp-extension` automatically. MCP servers live in `mcp.json`,
not `settings.toml`.

## Codex Sandbox Note

Codex tool sandboxes cannot always write under `$HOME` or the git repo root, so
the shared `shell_env` detects a writable workspace root when `CODEX_SANDBOX`
is set. It redirects `RTK_DB_PATH` there and forces thread-based execution to
avoid sandbox semaphore failures. Normal terminal sessions keep the default
RTK and CBM locations.

---

## File Layout

```
<template-root>/
├── agent/                            ← Agent runtime configuration only
│   ├── rules/                        ← Canonical operating and language rules
│   ├── instincts/                    ← Continuous learning skeleton
│   ├── reboot/                       ← Context recovery checklists
│   ├── prompts/                      ← Prompt-library registry + docs
│   ├── quality-gates/                ← Runtime quality-gate policy
│   ├── manifest.yaml
│   └── README.md
├── agent-skills/                     ← Skill supply chain; see its README
├── data-hub/                         ← Knowledge lifecycle backend; separate subsystem
├── scripts/
│   ├── install-agent-tooling.sh      ← Single config entry point
│   ├── agent-doctor.sh               ← Security + health check
│   ├── detect-package-manager.sh     ← PM auto-detection
│   ├── setup-mcp-profiles.sh         ← MCP disable mechanism
│   ├── add-hook-matchers.sh          ← Finer-grained hooks
│   ├── skill_supply_chain.py         ← Registry-driven skill fetch/audit/distribute/snapshot
│   ├── skill-refresh.sh              ← Thin compatibility wrapper around skill_supply_chain.py
│   └── sync-agent-prompts.sh         ← Prompt-library sync + index
├── Makefile                           ← All targets documented
└── README.md                          ← This file
```
