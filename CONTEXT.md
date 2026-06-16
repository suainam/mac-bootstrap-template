# mac-bootstrap — Domain Context

## Purpose

macOS development environment bootstrap. Installs CLI tools, desktop apps, agent tooling,
and configurations via Homebrew + shell scripts. Designed to be rerunnable and idempotent.
Terminal workflow now prefers tmux. The first verification path is
`make tmux-workspace`, which enters the AI layout through the same shell startup
path used by day-to-day work. Hammerspoon is the system-control tier. Keep its
hotkeys global and Hyper-based; keep tmux pane keys local to the terminal so
the two layers do not fight.

## Bootstrap Phases

| Phase | Script | What happens |
|-------|--------|-------------|
| Brew | `Brewfile` + `brew-bundle.sh` | Homebrew formulae, casks, npm packages, fonts |
| Shell | `install.sh` | Shell config (zsh), git, vim, tmux, VS Code |
| Docker | `infra/docker/install.sh` | Colima VM, 9Router proxy, Docker Compose |
| Agent | `install-agent-tooling.sh` | Skills, MCP, RTK, caveman, Pi config, CRG |
| Pi | `install-pi-packages.sh` | Pi-native packages (from `pi-packages.txt`) |

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

## Agent Architecture

6 managed agents: Claude Code, Codex CLI, OpenCode, Pi, Reasonix, Antigravity.
Each has a path registry in `agent/agent-manifest.json`.
Skills are wired from upstream repos (ECC + Matt Pocock) via `sync-agent-upstreams.sh`.

The agent bootstrap path is now split by responsibility:

- `scripts/install-agent-tooling.sh` remains the top-level orchestrator.
- `scripts/lib/agent-shared.sh`, `scripts/lib/agent-manifest.sh`, and
  `scripts/lib/skill-wiring.sh` hold reusable shell logic.
- `scripts/render-codex-mcp-block.py` and
  `scripts/sync-codex-mcp-config.py` own idempotent Codex MCP rendering.
- `scripts/run-doctor-checks.py` and `scripts/doctor-manifest.json` make
  doctor checks data-driven from `Brewfile` instead of hardcoded case lists.

## Key Terms

- **Upstream**: remote skill repos cloned to `~/.agent/upstream/`
- **Promote**: whitelist a skill from upstream into `~/.agent/skills/`
- **ECC**: everything-claude-code — the primary upstream material library
- **Data file**: a standalone file holding a list of packages, skills, or mappings (not code)
