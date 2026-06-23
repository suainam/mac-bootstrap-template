# mac-bootstrap — Domain Context

## Purpose

macOS development environment bootstrap. Installs CLI tools, desktop apps, agent tooling,
and configurations via Homebrew + shell scripts. Designed to be rerunnable and idempotent.
Terminal workflow now prefers tmux. The first verification path is
`make tmux-workspace`, which enters the AI layout through the same shell startup
path used by day-to-day work. Hammerspoon is the system-control tier. Keep its
hotkeys global and Hyper-based; keep tmux pane keys local to the terminal so
the two layers do not fight. Input methods stay under macOS/user control rather
than Hammerspoon automation.

## Bootstrap Phases

| Phase | Script | What happens |
|-------|--------|-------------|
| Brew | `Brewfile` + `brew-bundle.sh` | Homebrew formulae, casks, npm packages, fonts |
| Shell | `install.sh` | Shell config (zsh), git, vim, neovim, tmux, VS Code |
| Docker | `infra/docker/install.sh` | Colima VM, 9Router proxy, Docker Compose |
| Agent | `install-agent-tooling.sh` | Skills, MCP, RTK, caveman, Pi config, CRG |
| Pi | `install-pi-packages.sh` | Pi-native packages (from `pi-packages.txt`) |
| Obsidian | `editors/obsidian/install.sh` | Vault-local templates and portable `.obsidian` config |
| Ghostty | `terminals/ghostty/repair-fonts.sh` | Re-register existing Liga SFMono Nerd Font files |

## Data Files Convention

Canonical package/config lists live in standalone data files, not inline in scripts.
This is the pattern established by `pi-packages.txt` and `skills-promote.txt`.

| Data file | Purpose |
|-----------|---------|
| `Brewfile` | Homebrew formula/cask/npm manifest |
| `agent/pi-packages.txt` | Pi package references |
| `agent/skills-promote.txt` | Agent skill promotion whitelist |
| `infra/python/requirements-common.txt` | Python data-analysis dependencies |
| `editors/vscode/extensions.txt` | VS Code extension IDs |
| `editors/obsidian/vault/` | Reusable Obsidian vault config and templates |

## Agent Architecture

6 managed agents: Claude Code, Codex CLI, OpenCode, Pi, Reasonix, Antigravity.
Each has a path registry in `agent/agent-manifest.json`.
Skills are wired from upstream repos (ECC + Matt Pocock + Khazix + Garden + Humanizer + Obsidian)
via `sync-agent-upstreams.sh`.

The agent bootstrap path is now split by responsibility:

- `scripts/install-agent-tooling.sh` remains the top-level orchestrator.
- `scripts/lib/agent-shared.sh`, `scripts/lib/agent-manifest.sh`, and
  `scripts/lib/skill-wiring.sh` hold reusable shell logic.
- `scripts/render-codex-mcp-block.py` and
  `scripts/sync-codex-mcp-config.py` own idempotent Codex MCP rendering.
- `scripts/run-doctor-checks.py` and `scripts/doctor-manifest.json` make
  doctor checks data-driven from `Brewfile` instead of hardcoded case lists,
  and also verify managed symlinks still point at the current template paths.

## Key Terms

- **Upstream**: remote skill repos cloned to `~/.agent/upstream/`
- **Promote**: whitelist a skill from upstream into `~/.agent/skills/`
- **ECC**: everything-claude-code — the primary upstream material library
- **Obsidian skills**: Kepano Obsidian skills promoted from `kepano/obsidian-skills`
- **Data file**: a standalone file holding a list of packages, skills, or mappings (not code)
