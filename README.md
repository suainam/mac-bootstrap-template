# mac-bootstrap 模板

> 中文导航：模板架构与公共边界见 `CONTEXT.md`；agent 修改规则见 `CLAUDE.md`；可复用专题说明见 `docs/README.md`。当前机器的真实配置、私有地址、订阅与实例运维说明属于私有父仓。

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

This installs Homebrew dependencies from `Brewfile`, links shell/git/vim/neovim/tmux
configuration, configures Docker/npm proxy settings, and runs safe cache cleanup.
It does not delete project virtual environments or files under `~/work`.
If Microsoft Edge or Clash Verge already exists under `/Applications` from a
manual install, bootstrap skips that cask instead of forcing a reinstall.
Manual app notes and `make doctor` cask overrides live in
[`docs/manual-apps.md`](docs/manual-apps.md).
VS Code is installed through Homebrew, and extensions are installed when the
`code` CLI is available.
Neovim / LazyVim notes live in `editors/neovim/README.md`.
Legacy Vim notes live in `editors/vim/README.md`.
Ghostty uses `Liga SFMono Nerd Font` as the primary font and pins CJK glyphs to
`PingFang SC` through codepoint maps. If macOS stops exposing the Homebrew font
to Ghostty, repair the existing install without adding a new font:

```bash
make ghostty-font-repair
```

Reusable Obsidian vault config lives in `editors/obsidian/`. Install it into a
vault explicitly:

```bash
make obsidian-kit VAULT=/path/to/vault
```

Proxy defaults are enabled from `~/.shell_env`. New shells start with
`proxy_on`, and you can resync shell + npm + git state with:

```bash
proxy-on
proxy-off
make proxy-on
make proxy-off
```

Migration note: this bootstrap now uses Ghostty as the primary terminal host
and tmux as the workspace/session layer. Hammerspoon is the global tier: reload, window
placement, clipboard helpers, and terminal launcher hotkeys live there.
Hammerspoon does not manage input methods. `tm` is terminal-local only.

For file work inside the terminal, `yazi`, `fzf`, and `neovim` work together
under a ghostty → tmux host:

- In neovim, `<leader>y` opens yazi at the current file; `<leader>Y` opens it
  in the nvim working directory. Selected files open in buffers with LSP sync.
- In the shell, `ff` uses fzf to pick a file (Tab for multi-select) and opens it
  in nvim; `fd` uses fzf to pick a directory and opens yazi there. `y` opens
  yazi and changes your cwd to the last directory you landed on when you quit.
- Inside tmux, `prefix + y` opens yazi in the current directory; `prefix + Y`
  opens yazi as a chooser and sends the selected file back to the focused nvim
  pane (or opens it in nvim). `eza` is the fast read-only lister.

For remote `code-server` deployment and repair notes, see
[`infra/code-server/README.md`](infra/code-server/README.md). That runbook
covers the expected remote directory, root-vs-coder runtime behavior, Dockerfile
rebuild pitfalls, and extension/debug checks.

Quick verify:

```bash
make tmux-workspace
tm list-keys
```

Shell startup reference:
- [`docs/shell-startup.md`](docs/shell-startup.md) covers `zshenv -> shell_env -> zshrc`
- tmux panes must start `/bin/zsh -il` so p10k and interactive plugins load on first boot

For verification, `~` is the most general entrypoint. It is fine for shell
syntax and auto-attach checks, and keeps the workflow closer to a normal new
terminal session.

AI coding CLIs are managed from this Brewfile where possible: `claude-code` and
`pi-coding-agent` are Homebrew packages, while Reasonix is installed as a global
npm package through Homebrew Bundle's `npm` support. Token/context helpers are
split the same way: RTK and `codex-threadripper` are installed from Homebrew
taps, and `context-mode` is installed as a global npm package. Antigravity CLI
follows the official Google installer instead of Homebrew cask packaging.

Machine-level npm globals are tracked in `template/agent/npm-global-packages.txt`.
Use `make npm-packages` to install missing entries, `make npm-packages-upgrade`
to refresh them in place, and `make doctor-agent` to verify the current machine
against that manifest. The manifest intentionally stores bare package names, and
`make doctor-agent` reports a missing prerequisite if `node`/`npm` is absent.

DevSpace is also wired in as the remote MCP sidecar for browser and CLI agents.
Use [`docs/devspace-local.md`](docs/devspace-local.md) for the local server,
Cloudflare Tunnel, LaunchAgent workflow, and web-UI troubleshooting links
including the ChatGPT-side DevSpace app creation walkthrough.

`~/work` is the umbrella workspace, not a single repo. Keep each real project as
its own git repository under `~/work/projects`, with its own `.envrc`, `.env`,
and runtime state.

## Public template + private overlay

This template repo should stay public-safe. It can be published directly, so do
not track real machine-specific configs such as subscription URLs, internal
hostnames, usernames, tokens, or private IPs here.

Public sharing may still go through `make export-public`, which copies a fresh
tree without git history and excludes everything listed in `.publicignore`.
That export path is for hygiene and history isolation, not for hiding private
tracked config that should never have lived here.

```bash
export MAC_BOOTSTRAP_PRIVATE_REPO="git@github.com:<you>/mac-bootstrap-private.git"
make private-sync
make render-configs
make privacy-audit
```

Optional private overlay files mirror repo-relative paths, for example:

```text
private/clash/work-mac.yaml
private/editors/neovim/ai.lua
private/infra/code-server/env.sh
private/python/odps_config.py
private/shell/ssh_config                 # Canonical ~/.ssh/config source
private/shell/ssh_config.d/<legacy-host>   # SSH host config (symlinked, see below)
private/shell/ssh_keys/<key>             # SSH keys (symlinked into ~/.ssh/keys/)
```

Host-specific deployment values should live in the matching private overlay
path. For example, `infra/code-server/install.sh` will source
`private/infra/code-server/env.sh` for `CODE_SERVER_HOST` and `CODE_SERVER_DIR`
before it falls back to shell environment variables.

### SSH config deploy strategy

`install.sh` deploys every file under `private/shell/ssh_config.d/` (or
`template/shell/ssh_config.d/` when no private overlay exists) as a **symlink**
inside `~/.ssh/config.d/`, which is included by `~/.ssh/config` via a wildcard
`Include`.

Use this boundary to keep SSH manageable over time:
- `private/shell/ssh_config`: canonical source for `~/.ssh/config`; deploy as a
  symlink. Fall back to `template/shell/ssh_config` only when no private
  override exists yet.
- `~/.ssh/config`: symlink only; one global entrypoint plus true machine-wide
  defaults only.
- `private/shell/ssh_config.d/<host>`: one file per host or host-group.
- `private/shell/ssh_keys/<key>`: private keys; they are deployed into `~/.ssh/`
  under `~/.ssh/keys/` as symlinks with mode `600`.
- `private/shell/ssh_keys/<key>.pub`: public keys; deployed with mode `644`.
- `~/.ssh/keys/`: runtime key directory; should contain symlinks only.

Avoid putting managed keys directly under `~/.ssh/`; keep the top-level clean
and reserve it for entrypoints, runtime directories, and dynamic state such as
`known_hosts`.

The default managed `~/.ssh/config` is intentionally minimal:

```sshconfig
Include ~/.colima/ssh_config
Include ~/.ssh/config.d/*
```

Host-specific identity and transport settings should stay in `ssh_config.d/`,
not in the top-level config.

Managed-vs-dynamic SSH boundary:
- Managed: `~/.ssh/config`, `~/.ssh/config.d/*`, `~/.ssh/keys/*`,
  `~/.ssh/connect-proxy.py`
- Dynamic/local-only: `~/.ssh/known_hosts`, `~/.ssh/agent/`, and transient
  control sockets like `~/.ssh/cm-*`
- Unexpected top-level files under `~/.ssh/` should fail `make ssh-verify`

Using symlinks instead of copies means:
- Editing the source file in this repo takes effect immediately — no need to
  re-run `install.sh`.
- There is a single source of truth; the deployed file and the repo file are
  the same inode.

File permission note: `chmod 600` is applied to the **source file** (in the
repo), not the symlink. On macOS, `chmod` on a symlink only changes the link
itself, not the target, so the canonical place to enforce permissions is the
source.

Common SSH flows:
- Deploy or refresh SSH assets: `make ssh-install`
- Verify deploy + permissions + `ssh -G`: `make ssh-verify`
- Generate a new key directly into `private/shell/ssh_keys/`:
  `make ssh-key-generate NAME=id_ed25519_github TYPE=ed25519`
- Import an existing key:
  `make ssh-key-import NAME=cc15_rsa SRC=~/Downloads/cc15_rsa`
- Paste a key and fix permissions automatically:
  `pbpaste | make ssh-key-import-stdin NAME=cc15_rsa`

The `~/.ssh/config.d/<legacy-host>` host entry can include keepalive settings to
prevent idle disconnection from older bastions (`TERM-SSHD`):

```
ServerAliveInterval 60    # send a keepalive packet every 60 s
ServerAliveCountMax 10    # drop after 10 missed replies (~10 min of silence)
```

Clash profile flow:

- `template/proxy/clash/Merge.yaml` is the checked-in public working default.
- `template/proxy/clash/Merge.yaml.template` is the lower-level fallback seed.
- `private/clash/work-mac.yaml` is the private machine-specific source of truth
  for this Mac.
- Runtime profiles under `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles/` are generated state.
- Refreshing a Clash subscription does not rewrite `proxy/clash/Merge.yaml`; it only
  updates app-managed runtime state.
- `make render-configs` no longer copies `private/clash/work-mac.yaml` back into
  `template/proxy/clash/Merge.yaml`; private overrides sync only to the runtime profile.
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

1. Commit public-safe template changes here.
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
make bootstrap       # Brewfile + shell/vim/neovim/tmux
make npm-packages    # Install tracked global npm CLIs (context-mode, CBM, reasonix, ...)
make agent-sync      # Ensure missing skill bundles + sync prompt libraries
make agent-tools     # Wire RTK, caveman, managed MCPs, and skills for all agents
make agent-refresh   # Full sync + full agent reconfigure
make skill-refresh   # Ensure missing bundles + re-wire managed skills
make prompt-sync     # Sync prompt libraries + rebuild prompt index
make doctor-agent    # Verify all configs (contains AgentShield scan)
```

## Checks

```bash
make check
make ci
make doctor
make doctor-agent    # Agent health check (symlinks, config files)
make privacy-audit   # Redacted scan of tracked files
```

`make ci` is the public, reproducible validation contract used by GitHub
Actions. It runs syntax checks, pytest, the privacy audit, the skill registry
check, and the neat-freak documentation-alignment gate. It does not inspect
local applications, GUI state, accounts, or generated agent runtime state.

`make check` validates shell syntax, data-driven doctor checks, and runs the
template pytest suite from `template/.venv`. If `pytest-cov` is installed in the
local venv, the check also emits coverage for the extracted Python helper
scripts.
`make doctor` prints diagnostics without failing.
`make doctor-agent` verifies managed symlinks against the current template
targets, so directory refactors surface as stale-link failures instead of
silently leaving old dotfile paths in place.
`make doctor` also checks Chrome Gemini/Glic state when the local Chrome profile
is eligible, so a missing Gemini launcher or incomplete first-run setup surfaces
with the rest of the machine health report.

OpenWiki rollout has been withdrawn. Do not treat generated repo wiki pages as
the authority for repo rules or runbooks; keep `README.md`, `CONTEXT.md`,
`CLAUDE.md`, and `docs/` as the maintained sources of truth. Rationale is
captured in `docs/openwiki-boundary-decision.md`.

Regression notes:
- Do not parallelize `make -C template check` and parent `make check`; the
  `claude-daemon` tests can collide on the live lock file and produce false
  `SKIP: another instance running` failures.
- Tmux assertions query the live tmux socket. If a sandboxed run cannot access
  `/private/tmp/tmux-*`, rerun the check outside the sandbox instead of editing
  tmux config blindly.
- If tmux panes show only the fallback zsh prompt, inspect
  [`docs/shell-startup.md`](docs/shell-startup.md) before changing p10k. The
  usual failure mode is startup path drift, not the theme itself.

## Claude daemon

`launchd/io.local.mac-bootstrap.claude-daemon.plist` runs
`scripts/claude-daemon-tmux.sh` at `00:00`, `08:00`, and `15:00`.

- Structured run summaries go to `~/Library/Logs/claude-daemon/tmux.log`
- Raw `claude -p` stdout/stderr go to `/tmp/claude-daemon-tmux.log` and
  `/tmp/claude-daemon-tmux.err`
- `/tmp/claude-daemon-tmux.log` is best treated as the latest raw run only;
  use `~/Library/Logs/claude-daemon/tmux.log` for multi-day history
- For a one-off multi-line drill prompt, create `~/.claude/claude-daemon-prompt.txt`;
  the daemon will prefer that file over the default keepalive prompt
- Remove that file after the drill so scheduled runs return to the default
  keepalive behavior

## Agent tooling

Template subsystem boundaries:

- `agent/`: agent runtime configuration, rules, prompts, extensions, and quality gates
- `agent-skills/`: Skill source registry, local Skill sources, external quarantine, and distribution targets
- `data-hub/`: knowledge persistence, SQLite state, lifecycle workflows, summaries, and projections

The global `knowledge-lifecycle-manager` Skill is the Data Hub control entrypoint; implementation and subsystem runbooks live under [`data-hub/`](data-hub/README.md).

```bash
make agent-tools
make skill-refresh
```

This configures all agent-facing tools via `scripts/install-agent-tooling.sh`:
- Symlinks canonical config files from `agent/rules/` to agent home dirs
- RTK global hook, Codex config, OpenCode plugin, Pi extension
- Context Mode Claude plugin + OpenCode plugin
- Caveman with **ultra** mode for Claude, Codex, OpenCode, and Pi
- Agent quality gate policy + runner wiring
- Codebase Memory MCP installer with auto_index config
- 12 operating rules embedded in all agent system prompts
- Finer-grained hook matchers (console.log guards, destructive op warnings)
- Codex MCP startup policy and the `codex-mcp` on-demand launcher
- Legacy ECC MCP exclusion support through `ECC_DISABLED_MCPS`

Quality gate model:
- `pre-commit` is the fast path for scoped checks
- `pre-push` is the authoritative path for heavy validation and knowledge recording
- installed Codex hooks are adapters; repo-owned scripts execute the actual gate logic

Skill management rule:
- Treat `template/agent-skills/registry/sources.jsonc` as source lineage,
  scope, gate, and project-routing authority
- Treat `template/agent-skills/registry/targets.jsonc` as agent/app target authority
- Treat `template/agent-skills/local/` as tracked local Skill sources
- Treat `template/agent-skills/external/quarantine/` as ignored fetched input
- Treat project `.agents/skills/` dirs as generated symlink views, not source
- Treat `~/.agent/skills/` as generated shared state
- Treat `~/.claude/skills`, `~/.codex/skills`, and other app skill dirs as
  generated consumer views

Distribution helpers:

```bash
make skill-plan
make skill-check
python3 scripts/skill_supply_chain.py distribute --dry-run
make skill-snapshot LABEL=pre-change
```

Prompt library helpers:

```bash
make prompt-sync
make prompt-list Q=analyze
make prompt-mcp
agent-prompt show fabric:extract_wisdom
```

Prompt libraries follow the same generated-state split as skills:
- Treat `template/agent/prompts/sources.json` as the canonical source registry
- Treat upstream prompt repos under `~/.agent/upstream/` as synced external material
- Treat `~/.agent/prompts/index.json` as generated lookup state for agents and MCPs
- Keep SQLite/vector indexes as generated caches only, if needed later
- Use [`docs/agent-prompt-mcp.md`](docs/agent-prompt-mcp.md) for Codex MCP
  setup, JSON-RPC smoke tests, and troubleshooting

## Architecture

See [`agent/README.md`](agent/README.md) for the complete architecture guide:
- How skills/MCPs are wired across agents
- How to add new skills and MCP servers
- Agent config matrix (what's configured where)
- When to split work across deploy, troubleshoot, and test subagents:
  [`docs/agent-subagents.md`](docs/agent-subagents.md)
- ECC feature borrowings
- Reasonix and Pi integration details

## Quick targets

| Target | What |
|--------|------|
| `make bootstrap` | Brewfile + shell/vim/neovim/tmux config |
| `make agent-tools` | Wire all agent tools |
| `make agent-refresh` | Full sync + full agent reconfigure |
| `make skill-refresh` | Ensure missing bundles + re-wire managed skills |
| `make prompt-sync` | Sync prompt libraries + rebuild prompt index |
| `make check` | Syntax + tool validation |
| `make ci` | Public CI contract: syntax, pytest, privacy, skill, and docs gates |
| `make doctor` | Machine health check |
| `make doctor-agent` | Agent health check |
| `make security-scan` | AgentShield audit |
| `make privacy-audit` | Redacted current-tree privacy scan |
| `make privacy-audit-history` | Redacted git-history privacy scan |
| `make private-sync` | Clone/update ignored private overlay repo |
| `make export-public DEST=/path` | Export tracked template files without git history |
| `PUBLIC_REPO=owner/repo make publish-public` | Export and push the public template |
| `make agent-sync` | Ensure missing skill bundles + sync prompt libraries |
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

Keep `workspace/scripts/odps-export` and `workspace/scripts/odps-export-runner.py`
deployed as a pair. The wrapper now fails fast if the runner is missing.
Export specs may use inline `sql` or `sql_file`, select named exports with
`--select name[,name]`, and template `${param}` values from spec `params`,
default `today`/`yesterday`, or repeated `--param KEY=VALUE` overrides.

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
