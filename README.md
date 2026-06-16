# mac-bootstrap

New-machine bootstrap for this Mac setup.

## Cold Start (Fresh Mac Without Proxy)

On a fresh Mac behind GFW, `git clone`, `brew install`, and `curl github.com` all
fail. This one-liner uses a GitHub mirror to download Clash Verge — no proxy
needed:

```bash
curl -fsSL https://gh-proxy.com/https://github.com/suainam/mac-bootstrap-template/raw/main/scripts/install-clash.sh | bash
```

Then:

1. Open **Clash Verge** from Applications
2. Import your subscription URL (paste into Profiles → Import)
3. Enable System Proxy (toggle in the app)
4. Verify proxy works:

```bash
curl -I https://github.com   # should return 200
```

5. Set proxy env vars in current terminal (Clash Verge default port is 7897):

```bash
export http_proxy=http://127.0.0.1:7897
export https_proxy=http://127.0.0.1:7897
export all_proxy=socks5://127.0.0.1:7897
```

6. Continue bootstrap:

```bash
# For the public template only:
git clone https://github.com/suainam/mac-bootstrap-template.git ~/work/config/mac-bootstrap-template
cd ~/work/config/mac-bootstrap-template
make bootstrap

# Or with private overlay (requires access to private repo):
git clone --recursive https://github.com/suainam/mac-bootstrap.git ~/work/config/mac-bootstrap
cd ~/work/config/mac-bootstrap/template
make bootstrap
```

Preview mode (no install):

```bash
curl -fsSL https://gh-proxy.com/https://github.com/suainam/mac-bootstrap-template/raw/main/scripts/install-clash.sh | bash -s -- --dry-run
```

If mirror is down, try alternative mirrors:

```bash
# Replace gh-proxy.com with one of: ui.ghproxy.cc, github.akams.cn, www.gitwarp.com
curl -fsSL https://ui.ghproxy.cc/https://github.com/suainam/mac-bootstrap-template/raw/main/scripts/install-clash.sh | bash
```

## One command (with proxy already working)

```bash
make bootstrap
```

This installs Homebrew dependencies from `Brewfile`, links shell/git/vim/tmux
configuration, configures Docker/npm proxy settings, and runs safe cache cleanup.
It does not delete project virtual environments or files under `~/work`.
If Microsoft Edge or Clash Verge already exists under `/Applications` from a
manual install, bootstrap skips that cask instead of forcing a reinstall.
VS Code is installed through Homebrew, and extensions are installed when the
`code` CLI is available.

Proxy defaults are enabled from `~/.shell_env`. New shells start with
`proxy_on`, and you can resync shell + npm + git state with:

```bash
proxy-on
proxy-off
make proxy-on
make proxy-off
```

Migration note: this bootstrap now uses iTerm2 as the terminal host and tmux
as the workspace/session layer. Hammerspoon is the global tier: reload, window
placement, clipboard helpers, and terminal launcher hotkeys live there. `tm`
is terminal-local only.

Quick verify:

```bash
make tmux-workspace
tm list-keys
```

For verification, `~` is the most general entrypoint. It is fine for shell
syntax and auto-attach checks, and keeps the workflow closer to a normal new
terminal session.

AI coding CLIs are managed from this Brewfile where possible: `claude-code` and
`pi-coding-agent` are Homebrew packages, while Reasonix is installed as a global
npm package through Homebrew Bundle's `npm` support. Token/context helpers are
split the same way: RTK and `codex-threadripper` are installed from Homebrew
taps, and `context-mode` is installed as a global npm package. Antigravity CLI
follows the official Google installer instead of Homebrew cask packaging.

`~/work` is the umbrella workspace, not a single repo. Keep each real project as
its own git repository under `~/work/projects`, with its own `.envrc`, `.env`,
and runtime state.

## Public template + private overlay

This working repo is expected to stay private. It may track real
machine-specific configs such as `proxy/clash/Merge.yaml`.

Public sharing must go through `make export-public`, which copies a fresh tree
without git history and excludes everything listed in `.publicignore`.
Templates and examples are exported; subscription URLs, AI keys, usernames, IPs,
handoff notes, and local config files are not.

Do not make this private repo or its history public. Publish only the generated
public template tree.

```bash
export MAC_BOOTSTRAP_PRIVATE_REPO="git@github.com:<you>/mac-bootstrap-private.git"
make private-sync
make render-configs
make privacy-audit
```

Optional private overlay files mirror repo-relative paths, for example:

```text
private/clash/Merge.yaml
private/python/odps_config.py
```

Clash profile flow:

- `template/proxy/clash/Merge.yaml` is the checked-in public working default.
- `template/proxy/clash/Merge.yaml.template` is the lower-level fallback seed.
- `private/clash/Merge.yaml` is the private machine-specific override.
- Runtime profiles under `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles/` are generated state.
- Refreshing a Clash subscription does not rewrite `proxy/clash/Merge.yaml`; it only
  updates app-managed runtime state.
- Full notes: [`docs/clash-profile-flow.md`](docs/clash-profile-flow.md)

Use `make export-public DEST=/path/to/mac-bootstrap-public` to produce a
history-free public template copy. If this private repo history ever contained
real secrets or subscription URLs, do not publish that history; export a fresh
public repo and rotate any exposed credentials.

To publish or refresh the public GitHub template:

```bash
PUBLIC_REPO=<you>/mac-bootstrap-template make publish-public
```

Recommended workflow:

1. Commit real config changes here in the private repo.
2. Run `make privacy-audit`.
3. Run `PUBLIC_REPO=<you>/mac-bootstrap-template make publish-public`.

## Private repo with public submodule

For long-term reuse, keep your private repo as the parent and add the public
template as a submodule:

```text
mac-bootstrap-private/
  template/   # public mac-bootstrap-template submodule
  private/    # real configs, keys, subscription URLs, usernames, IPs
  bootstrap.sh
```

The parent `bootstrap.sh` can be as small as:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export MAC_BOOTSTRAP_PRIVATE_DIR="$ROOT/private"
exec "$ROOT/template/install.sh" "$@"
```

`scripts/render-configs.sh` automatically prefers `MAC_BOOTSTRAP_PRIVATE_DIR`,
then `../private`, then local templates. So cloning the private parent with
submodules is enough to run the real setup:

```bash
git clone --recursive <private-repo>
cd mac-bootstrap-private
./bootstrap.sh --yes
```

The workspace entrypoints (`~/work/Makefile`, `~/work/PROJECTS_GUIDE.md`, and
`~/work/scripts`) are managed from this repo under `workspace/` and linked into
place during bootstrap.

For non-interactive git identity setup:

```bash
GIT_NAME="Your Name" GIT_EMAIL="you@example.com" make bootstrap
```

## Full setup (including agent tools)

```bash
make bootstrap       # Brewfile + shell/vim/Zellij
make agent-sync      # Clone upstream skills (ECC + Matt Pocock) 
make agent-tools     # Wire RTK, caveman, CBM, context-mode, skills for all agents
make agent-refresh   # Full sync + full agent reconfigure
make skill-refresh   # Sync upstreams + re-wire skills only
make doctor-agent    # Verify all configs (contains AgentShield scan)
```

## Checks

```bash
make check
make doctor
make doctor-agent    # Agent health check (symlinks, config files)
make privacy-audit   # Redacted scan of tracked files
```

`make check` validates shell syntax, data-driven doctor checks, and runs the
template pytest suite with coverage for the extracted Python helper scripts.
`make doctor` prints diagnostics without failing.

## Agent tooling

```bash
make agent-tools
make skill-refresh
```

This configures all agent-facing tools via `scripts/install-agent-tooling.sh`:
- Symlinks canonical config files from `agent/rules/` to agent home dirs
- RTK global hook, Codex config, OpenCode plugin, Pi extension
- Context Mode Claude plugin + OpenCode plugin
- Caveman with **ultra** mode for Claude, Codex, OpenCode, and Pi
- Codebase Memory MCP installer with auto_index config
- 12 operating rules embedded in all agent system prompts
- Finer-grained hook matchers (console.log guards, destructive op warnings)
- MCP profile system (`ECC_DISABLED_MCPS` env var)

Skill management rule:
- Treat `template/agent/skills/` + `template/agent/skills-promote.txt` as the only
  canonical source
- Treat `template/agent/skills-distribution.json` as the canonical app-routing map
- Treat `~/.agent/skills/` as generated shared state
- Treat `~/.claude/skills`, `~/.codex/skills`, and other app skill dirs as
  generated consumer views

Distribution helpers:

```bash
make skill-route SKILL=aihot APPS=codex,opencode
make skill-route-list
make skill-refresh
```

## Architecture

See [`agent/README.md`](agent/README.md) for the complete architecture guide:
- How skills/MCPs are wired across agents
- How to add new skills and MCP servers
- Agent config matrix (what's configured where)
- ECC feature borrowings
- Reasonix and Pi integration details

## Quick targets

| Target | What |
|--------|------|
| `make bootstrap` | Brewfile + shell/vim/Zellij config |
| `make agent-tools` | Wire all agent tools |
| `make agent-refresh` | Full sync + full agent reconfigure |
| `make skill-refresh` | Sync upstreams + re-wire skills only |
| `make check` | Syntax + tool validation |
| `make doctor` | Machine health check |
| `make doctor-agent` | Agent health check |
| `make security-scan` | AgentShield audit |
| `make privacy-audit` | Redacted current-tree privacy scan |
| `make privacy-audit-history` | Redacted git-history privacy scan |
| `make private-sync` | Clone/update ignored private overlay repo |
| `make export-public DEST=/path` | Export tracked template files without git history |
| `PUBLIC_REPO=owner/repo make publish-public` | Export and push the public template |
| `make agent-sync` | Sync upstream ECC/Pocock skills |
| `make pm-detect` | Detect package manager |
| `make pm-set PNPM` | Set global package manager |
| `make clean-cache` | Prune build caches |
| `make cache-report` | Show largest cache directories |
| `make install-cache-agent` | Install weekly cache cleanup job |
| `make organize-downloads` | Sort files from `~/Downloads` |
| `make install-downloads-agent` | Install auto-organizer for downloads |

## Cache cleanup

```bash
make clean-cache
make clean-cache-aggressive
make cache-report
make install-cache-agent
```

The cleanup script only prunes rebuildable tool caches through supported tool
commands. Safe mode runs `uv cache prune` and `brew cleanup -s`. Aggressive
mode also purges `npm` and `pip` caches. It intentionally skips project
`.venv` directories, `~/work` data, Codex runtime caches, and browser profiles.

`make install-cache-agent` installs a LaunchAgent that runs safe cleanup every
Sunday at 04:15 and writes logs to `/tmp/mac-bootstrap-cache-cleanup.log`.

## Project-local envs

Keep shared shell defaults in `~/work/.envrc`, but keep Python/node/runtime
activation inside each project.

- `~/work/.envrc`: workspace-wide variables only
- `~/work/projects/<name>/.envrc`: project-local activation + `dotenv`
- `~/work/projects/<name>/.env`: secrets and per-project ports

To scaffold a new project:

```bash
./scripts/new-project.sh
```

To scaffold a new analysis subproject inside an existing repo:

```bash
~/work/scripts/new-analysis-subproject \
  ~/work/projects/analysis-program \
  sales \
  demand_forecast
```

The scaffold creates:
- project-local `.envrc` with `dotenv_if_exists .env`
- `.env.example` and `.env`
- a fresh git repository on `main`
- a conservative `.gitignore` for data files, Office docs, images, caches, and temp outputs

The analysis-subproject scaffold creates:

- `docs/`, `scripts/`, `sql/`, `data/`, `outputs/`, `notebooks/`, `skills/`
- `Makefile` with a standard `odps-export` entrypoint
- `odps_export_config.py` for project-local export specs
- a README that assumes repo-level `uv` management and shared Docker/ODPS helpers

Data directories in the Docker Compose setup:

| Host path | Container path | Scope | Access |
|-----------|----------------|-------|--------|
| `./data/` | `/workspace/data` | project-local data | read-write |
| `~/work/data` | `/workspace/shared-data` | shared workspace data | read-only |

Use lowercase `data/` for both workspace and project data directories. Inside
containers, read shared data through `SHARED_DATA_DIR=/workspace/shared-data`.

See [`PROJECTS_GUIDE.md`](workspace/PROJECTS_GUIDE.md) for the full data placement rules.

## Download organization

```bash
make organize-downloads
make install-downloads-agent
```

`make organize-downloads` moves files out of `~/Downloads` but never deletes
them.

- WeCom / enterprise-sharing style files go to `~/work/data/downloads/wecom`
- Browser installers (`.dmg`, `.pkg`, etc.) go to `~/work/tmp/downloads/browser/software`
- Browser docs, archives, images, and media go to matching browser subfolders
- Unknown files go to `~/work/tmp/downloads/unsorted`

The organizer uses source metadata when macOS provides it, then falls back to
filename patterns and file extensions. `make install-downloads-agent` installs a
LaunchAgent that runs every 30 minutes and logs to:

- `/tmp/mac-bootstrap-downloads-organizer.log`
- `/tmp/mac-bootstrap-downloads-organizer.err`
