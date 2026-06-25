# Agent Tooling — Architecture & Usage Guide

## One-Command Setup

```bash
# From bootstrap repo root:
make bootstrap   # Brewfile deps + shell/vim/neovim/tmux config
make agent-sync  # Clone upstream skills (ECC + Matt Pocock + Khazix + Garden + Humanizer + Obsidian → ~/.agent/skills/)
make agent-tools # Configure RTK, caveman, CRG, context7 + wire skills for all agents
make agent-refresh # Full sync + full agent reconfigure
make skill-refresh # Sync upstreams + re-wire skills only
make prompt-sync # Sync Fabric/Wonderful prompt libraries + rebuild index
make prompt-mcp  # Run prompt-library MCP stdio server
make doctor-agent # Verify all configs
make security-scan  # AgentShield security audit
```

All agent configs are driven from [`agent/agent-manifest.json`](agent-manifest.json).
Edit the manifest or canonical files once, then re-run `make agent-tools`.
Generated runtime markdown files are intentionally short and ordered:
`12-rules` first, then `RTK`, then `CRG / docs`.

---

## Architecture

### Canonical Sources

```
bootstrap/agent/agent-manifest.json   ← Agent locations + config targets (edit here)
bootstrap/agent/rules/12-rules.md     ← Canonical instruction source
  → ~/.claude/12-rules.md            ← Symlink (Claude @include reads it)
  → ~/.codex/AGENTS.md @/path/ref    ← Codex reads via @/path/to/file
  → ~/.pi/agent/AGENTS.md @~/.claude/12-rules.md  ← Pi reads via AGENTS.md ref
  → ~/.claude/CLAUDE.md @12-rules.md              ← Reasonix inherits via Claude docs
  → ~/.claude/CLAUDE.md @RTK.md                   ← RTK follows 12-rules

bootstrap/agent/rules/common/         ← Canonical rules dir
  → ~/.claude/rules/common/          ← Claude Code auto-loads rules

bootstrap/agent/rules/python/         ← Canonical python rules
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
- Caveman default mode (`~/.config/caveman/config.json`)
- Pi `settings.json` + `mcp.json` + AGENTS.md ref
- Reasonix config.json + skills
- Antigravity `settings.json` + `mcp_config.json` + skills
- Workspace `GEMINI.md` + `REASONIX.md` generated from canonical rules
- OpenCode plugin list (rtk, caveman, context-mode)
- MCP profiles (`~/.zshrc`)
- Hook matchers (console.log guards, destructive op warnings)
- **Skill wiring**: Symlinks upstream skills (ECC + Matt Pocock + Obsidian + personal) from
  `~/.agent/skills/` into each agent's skills directory per the documented format:

The script is intentionally split by responsibility:

- `scripts/install-agent-tooling.sh` — thin step runner / orchestration only
- `scripts/lib/agent-shared.sh` — shell helpers (run/try_run, managed block writes)
- `scripts/lib/agent-manifest.sh` — manifest/path resolution
- `scripts/lib/agent-mcp.sh` — shared MCP/JSON config writers
- `scripts/lib/agent-configure.sh` — per-step agent/platform configuration bodies
- `scripts/lib/skill-wiring.sh` — shared upstream-skill routing
- `scripts/sync-agent-prompts.sh` + `scripts/agent-prompt-index.py` — prompt-library sync/index
- `scripts/render-codex-mcp-block.py` + `scripts/sync-codex-mcp-config.py` — idempotent Codex MCP rendering/rewrite
- `scripts/run-doctor-checks.py` + `scripts/doctor-manifest.json` — data-driven doctor checks derived from Brewfile

---

## Agent Config Matrix

| Tool | Claude Code | Codex CLI | OpenCode | Pi | Reasonix | Antigravity |
|------|:-----------:|:---------:|:--------:|:--:|:--------:|:------------:|
| **RTK** | ✅ hook+RTK.md | ✅ RTK.md+AGENTS.md | ✅ plugin | ✅ extension + settings.json | ❌ | ❌ |
| **Caveman** | ✅ plugin+ultra | ✅ skills+hooks | ✅ plugin+ultra | ✅ skill file | ✅ skill file |
| **Context-mode** | ✅ plugin | ✅ hooks | ✅ plugin | ❌ | ❌ | ❌ |
| **CRG** | ✅ MCP | ✅ MCP in config.toml | ✅ MCP | ✅ `mcp.json` | ✅ MCP server | ✅ `mcp_config.json` |
| **12 Rules** | ✅ @12-rules.md | ✅ @/path ref | ✅ inline embedded | ✅ inline AGENTS.md | ✅ workspace `REASONIX.md` | ✅ workspace/global `GEMINI.md` |
| **ECC Skills** | ✅ dir symlinks | ✅ dir symlinks | ✅ via `~/.claude/` | ✅ dir symlinks | ✅ flat symlinks |
| **Pocock Skills** | ✅ dir symlinks | ✅ dir symlinks | ✅ via `~/.claude/` | ✅ dir symlinks | ✅ flat symlinks |
| **`.agents/skills/`** | ❌ | ✅ scan | ✅ scan | ✅ scan | ❌ | ❌ |

---

## Upstream Skills

Upstream skills are synced into `~/.agent/skills/upstream/` by `make agent-sync`:

```bash
make agent-sync   # Clone ECC + Matt Pocock + Khazix + Garden + Humanizer + Obsidian repos → promote whitelisted skills
make agent-tools  # Re-wire agent skill dirs
make agent-refresh # Full sync + full agent reconfigure
make skill-refresh # Preferred path for day-to-day skill maintenance
```

Then `make agent-tools` wires them as symlinks into each agent's skills dir.
The bootstrap repo is the skill SSOT. `~/.agent/skills/` is the shared build
artifact, and agent-specific skill dirs are consumer symlinks/copies only.
To add a new upstream skill to the whitelist, edit `agent/skills-promote.txt`
and re-run `make skill-refresh`.

First-party skills have two independent routing layers:

- Workspace scope: `agent/skills-manifest.json` chooses `global` or a project
  `.agents/skills/` symlink view.
- Agent routing: `agent/skills-distribution.json` chooses which apps receive a
  globally published skill.

The manifest does not route by agent. It only decides whether a first-party
skill is global or project-local. Upstream skills such as `grill-with-docs` and
`improve-codebase-architecture` stay remote-synced by
`scripts/sync-agent-upstreams.sh`; they are not copied into
`template/agent/skills/personal/`.

The manifest is intentionally grouped for low-friction maintenance:

- `source_root` points at the canonical first-party skill tree.
- `global_skills` lists names that publish into shared agent views.
- `projects.<name>.skills` lists names that should only appear in that
  project's `.agents/skills/`.

Minimal shape:

```json
{
  "version": 2,
  "source_root": "agent/skills/personal",
  "global_skills": ["cavecrew", "caveman"],
  "projects": {
    "playground": {
      "skills_dir": "${HOME}/work/projects/playground/.agents/skills",
      "skills": ["ottos-effect-analysis"]
    }
  }
}
```

Runtime helpers:

```bash
make skill-scope-refresh
make skill-route SKILL=aihot APPS=codex,opencode
make skill-route-show SKILL=aihot
make skill-route-clear SKILL=aihot
make skill-route-default APPS=claude,codex,opencode,pi,reasonix,antigravity,cross-agent
make skill-refresh
```

For personal skills:

```bash
template/agent/skills/personal/<skill>/SKILL.md   # create or edit source
agent/skills-manifest.json                        # add to global_skills or projects.<name>.skills
agent/skills-promote.txt                          # add/remove first-party publish name
agent/skills-distribution.json                    # optional agent routing for global skills
make skill-refresh
```

To delete a first-party skill, remove it from `agent/skills-manifest.json` and
`agent/skills-promote.txt`, delete the personal source dir if applicable, then
run `make skill-refresh`.

Source-of-truth split:

- Third-party upstream skills: `agent/skills-promote.txt` sections `everything-claude-code`, `mattpocock-skills`, `khazix-skills`, `garden-skills`, `humanizer-zh`, `obsidian-skills`
- First-party skills: `template/agent/skills/personal/`
- First-party workspace scope: `agent/skills-manifest.json`
- Agent/app distribution matrix: `agent/skills-distribution.json`
- Project skill views: repo-local `.agents/skills/<skill>` symlinks generated
  from the manifest

Skill source matrix:

| Source class | Canonical source | Admission control | Scope control | Agent control | Delivered by |
|-------|-----------------|-------------|-------------|-------------|-------------|
| First-party global | `template/agent/skills/personal/<skill>/` | Add name to `agent/skills-promote.txt` `personal` | Add name to `agent/skills-manifest.json` `global_skills` | Default all-apps, or override in `agent/skills-distribution.json` | `make skill-refresh` |
| First-party project | `template/agent/skills/personal/<skill>/` | Add name to `agent/skills-promote.txt` `personal` | Add name to `agent/skills-manifest.json` `projects.<name>.skills` | Not agent-routed; only the target project's `.agents/skills/` sees it | `make skill-refresh` |
| Upstream whitelisted | `~/.agent/skills/upstream/<source>/<skill>/` after sync | Add name to the matching section in `agent/skills-promote.txt` | Always global shared skill | Default all-apps, or override in `agent/skills-distribution.json` | `make skill-refresh` |
| Plugin / curated runtime skills | Plugin cache or bundled runtime, for example `.codex/plugins/cache/.../skills/...` | Managed by plugin/runtime install, not `skills-promote.txt` | Outside `skills-manifest.json` | Outside `skills-distribution.json` unless you copy/promote them into your own skill tree | Plugin/runtime itself |

Control notes:

- `agent/skills-distribution.json` only affects skills that `skill-refresh` wires into agent skill dirs.
- Plugin-curated skills such as `build-web-data-visualization:*` are visible only if the runtime/plugin exposes them; they are not part of the first-party or upstream-whitelist distribution flow.
- If a skill should behave like a managed global skill across Claude, Codex, OpenCode, Pi, Reasonix, Antigravity, and cross-agent, it must be in the `skill-refresh` pipeline rather than only existing inside a plugin cache.

| Agent | Wiring Mechanism | Example Path |
|-------|-----------------|-------------|
| Claude Code | Symlink dir → `~/.claude/skills/` | `~/.claude/skills/python-patterns/` |
| Codex CLI | Symlink dir → `~/.codex/skills/` | `~/.codex/skills/python-patterns/` |
| OpenCode | Symlink dir → `~/.config/opencode/skills/` + shared `~/.agents/skills/` | `~/.config/opencode/skills/python-patterns/` |
| Pi | Symlink dir → `~/.pi/agent/skills/` | `~/.pi/agent/skills/python-patterns/` |
| Antigravity | Symlink dir → `~/.gemini/antigravity-cli/skills/` | `~/.gemini/antigravity-cli/skills/python-patterns/` |
| Cross-agent | Symlink dir → `~/.agents/skills/` | `~/.agents/skills/python-patterns/` |
| Reasonix | Symlink flat `.md` → `~/.reasonix/skills/` | `~/.reasonix/skills/python-patterns.md` |

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

## Agent Skill Format Reference

Each agent follows the [Agent Skills standard](https://agentskills.dev) with
slight variations. Every skill is a directory containing `SKILL.md` with YAML
frontmatter:

```yaml
---
name: skill-name
description: "What this skill does and when to use it. Quote if it uses colons."
---
```

### Per-Agent Requirements

| Requirement | Claude Code | Codex CLI | OpenCode | Pi | Reasonix |
|-------------|:-----------:|:---------:|:--------:|:--:|:--------:|
| **Skill format** | dir | dir | dir | dir | flat `.md` |
| **Scan paths** | `~/.claude/skills/` | `~/.codex/skills/`<br>`~/.agents/skills/` | `~/.claude/skills/`<br>`~/.config/opencode/skills/`<br>`~/.agents/skills/` | `~/.pi/agent/skills/`<br>`~/.agents/skills/` | `~/.reasonix/skills/` |
| **`name` required** | No¹ | Yes | Yes | Yes | ? |
| **`description` required** | Recommended | Yes | Yes | Yes | ? |
| **Dir = name** | Recommended | Required | Required | Not required² | ? |
| **YAML strictness** | Lenient | Strict | Lenient | Lenient | ? |
| **Unknown fields** | Used | Error? | Ignored | Ignored | ? |

¹ Claude Code defaults `name` to directory name if omitted.
² Pi explicitly allows name != directory name for shared skill directories.

### Common Pitfalls

1. **Unquoted colons in description**: Codex CLI's YAML parser treats `: ` as
   a mapping separator. Always quote descriptions containing colons:
   ```yaml
   description: "Use for Python analysis: load, inspect, transform."
   ```
2. **Directory name ≠ frontmatter name**: OpenCode and Codex require the
   `name` field to match the directory name exactly. Pi does not enforce this.
3. **Flat `.md` vs directory format**: Claude Code, Codex CLI, and OpenCode
   require `~/.claude/skills/<name>/SKILL.md` (directory with SKILL.md file).
   Pi also uses this format. Reasonix uses flat `.md` files. Use the `wire_skill_dir`
   function in `install-agent-tooling.sh` to handle the conversion.

## Adding a New Skill

### For Claude Code (Plugin-based)

Skills installed as plugins (caveman, context-mode) through the plugin marketplace.
Skills in `~/.claude/skills/` with `SKILL.md` frontmatter are auto-loaded.

### For Codex CLI

Skills live in `~/.codex/skills/<name>/SKILL.md`:

```bash
mkdir -p ~/.codex/skills/my-skill/
cp myskill.md ~/.codex/skills/my-skill/SKILL.md
```

Or add a first-party skill to the bootstrap repo and publish it through the
manifest:

```bash
template/agent/skills/personal/my-skill/SKILL.md
template/agent/skills-manifest.json     # choose global or project scope
template/agent/skills-promote.txt       # include under personal
make skill-refresh
```

If the skill is in `~/.agent/skills/upstream/`, it is wired automatically by
`scripts/lib/skill-wiring.sh`. To add a new upstream skill, add its name to
`agent/skills-promote.txt` and run `make skill-refresh`.

### For Pi

Pi uses two mechanisms:

**Skills** — directory skills in `~/.pi/agent/skills/`. Created automatically
by `make agent-tools` for shared skills like caveman. Use `/skill new` inside Pi.

**Extensions** — TypeScript modules. Manage them from `~/.pi/agent/extensions/`
and list them in `~/.pi/agent/settings.json`. One-off registration still works:

```bash
pi install ~/.pi/agent/extensions/my-extension.ts
```

The RTK extension is at `~/.pi/agent/extensions/rtk.ts`. The bootstrap script
adds it to `settings.json` and also runs `pi install` when needed.

### For Reasonix

Skills go in `~/.reasonix/skills/` (global) or `<project>/.reasonix/skills/` (project):

```bash
/skill new my-skill              # Project-level
/skill new my-skill --global     # Global (~/.reasonix/skills/)
```

---

## Adding a New MCP Server

### Claude Code

Two ways:
1. Plugin marketplace (if bundled with a plugin)
2. `~/.claude/settings.json` MCP section or `~/.claude/.mcp.json`

### OpenCode

Edit `~/.config/opencode/opencode.json` — config key is `"plugin"` (singular):

```json
{
  "plugin": ["./plugins/rtk.ts", "./plugins/caveman/plugin.js"],
  "mcp": {
    "my-server": {
      "enabled": true,
      "type": "local",
      "command": ["npx", "-y", "my-mcp-server"]
    }
  }
}
```

### Codex CLI

Edit `~/.codex/config.toml`:

```toml
[mcp_servers.my-server]
command = "npx -y my-mcp-server"
```

### Pi

Edit `~/.pi/agent/mcp.json` (global) or `.pi/mcp.json` (project):

```json
{
  "mcpServers": {
    "my-server": {
      "command": "my-mcp-server"
    }
  }
}
```

### Reasonix

Edit `~/.reasonix/config.json` or use `/mcp add` inside Reasonix:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "npx -y my-mcp-server"
    }
  }
}
```

### Disabling MCPs Per Project

Set the `ECC_DISABLED_MCPS` env var to skip specific MCPs:

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
| 4 | **MCP Profiles** | `export ECC_DISABLED_MCPS="server1,server2"` |
| 5 | **PM Detection** | `make pm-detect` — 6-level priority chain |
| 6 | **Hook Matchers** | PreToolUse guards for console.log/destructive ops |
| 7 | **Eval Loop** | Skill at `~/.agent/skills/personal/eval-loop/SKILL.md` |

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
CRG + context7 MCP and caveman skill. Rules come from `~/.claude/CLAUDE.md`.

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
`pi-mcp-extension` installed, local OpenAI-compatible provider wired, CRG +
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
is set. It redirects `RTK_DB_PATH` there, sets `CRG_DATA_DIR` there when
needed, and forces `CRG_PARSE_EXECUTOR=thread` to avoid sandbox semaphore
failures during `code-review-graph build`. Normal terminal sessions keep the
default RTK and CRG locations.

---

## File Layout

```
bootstrap/
├── agent/
│   ├── rules/
│   │   ├── 12-rules.md              ← Canonical 12 operating rules
│   │   ├── common/                   ← ECC-style common rules
│   │   │   ├── testing.md
│   │   │   └── README.md
│   │   └── python/                   ← Python-specific rules
│   │       └── python-standards.md
│   ├── instincts/                    ← Continuous learning skeleton
│   │   └── README.md
│   ├── reboot/                       ← Context recovery checklists
│   │   ├── README.md
│   │   └── compact.md
│   ├── skills/
│   │   ├── personal/                 ← First-party skill source tree
│   │   │   ├── cavecrew/
│   │   │   ├── caveman/
│   │   │   ├── python-data-analysis/
│   │   │   ├── sql-analysis/
│   │   │   ├── marimo-analysis/
│   │   │   ├── docker-data-project/
│   │   │   └── eval-loop/
│   │   └── upstream/                 ← Upstream skills (via agent-sync)
│   ├── skills-manifest.json          ← First-party global/project scope
│   ├── skills-promote.txt            ← Upstream whitelist + first-party list
│   ├── skills-distribution.json      ← Agent/app routing map
│   ├── prompts/                      ← Prompt-library registry + docs
│   ├── manifest.yaml
│   └── README.md
├── scripts/
│   ├── install-agent-tooling.sh      ← Single config entry point
│   ├── agent-doctor.sh               ← Security + health check
│   ├── detect-package-manager.sh     ← PM auto-detection
│   ├── setup-mcp-profiles.sh         ← MCP disable mechanism
│   ├── add-hook-matchers.sh          ← Finer-grained hooks
│   ├── sync-agent-upstreams.sh       ← ECC & upstream skill sync
│   ├── skill-scope-refresh.sh        ← Project .agents/skills symlink views
│   └── sync-agent-prompts.sh         ← Prompt-library sync + index
├── Makefile                           ← All targets documented
└── README.md                          ← This file
```
