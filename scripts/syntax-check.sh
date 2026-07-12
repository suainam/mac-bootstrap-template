#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-.venv/bin/python}"
LUAC="${LUAC:-luac}"

for script in \
  install.sh \
  scripts/syntax-check.sh \
  scripts/neat-freak-ci.sh \
  scripts/brew-bundle.sh \
  scripts/configure-proxies.sh \
  scripts/clear-proxies.sh \
  scripts/clean-cache.sh \
  scripts/cache-report.sh \
  scripts/install-cache-cleanup-agent.sh \
  scripts/organize-downloads.sh \
  scripts/install-downloads-organizer-agent.sh \
  scripts/install-antigravity-cli.sh \
  scripts/doctor.sh \
  scripts/install-agent-tooling.sh \
  scripts/install-llm-wiki.sh \
  scripts/install-npm-global-packages.sh \
  scripts/lib/proxy-common.sh \
  scripts/lib/agent-shared.sh \
  scripts/lib/agent-manifest.sh \
  scripts/lib/agent-mcp.sh \
  scripts/lib/agent-configure.sh \
  scripts/lib/skill-wiring.sh \
  scripts/sync-private-overlay.sh \
  scripts/privacy-audit.sh \
  scripts/export-public-template.sh \
  scripts/publish-public-template.sh \
  scripts/new-project.sh \
  scripts/ssh-manage.sh \
  scripts/sync-agent-prompts.sh \
  scripts/agent-prompt.sh \
  scripts/agent-prompt-mcp.sh \
  scripts/agent-doctor.sh \
  editors/vscode/install-extensions.sh \
  editors/vim/install.sh \
  editors/vim/switch-theme.sh \
  editors/neovim/install.sh \
  editors/obsidian/install.sh \
  multiplexer/tmux/install.sh \
  multiplexer/tmux/switch-theme.sh \
  terminals/ghostty/install.sh \
  terminals/ghostty/repair-fonts.sh \
  terminals/iterm2/install.sh \
  terminals/iterm2/switch-theme.sh \
  desktop/hammerspoon/install.sh \
  scripts/install-imgup.sh \
  scripts/imgup.sh \
  scripts/claude-daemon-tmux.sh \
  scripts/tmux-workspace.sh \
  scripts/switch-terminal-theme.sh \
  scripts/agent-quality-gate.sh \
  scripts/neat-freak-gate.sh \
  scripts/knowledge-record-gate.sh \
  scripts/devspace-local.sh \
  scripts/devspace-supervisor.sh \
  scripts/devspace-tunnel-supervisor.sh \
  scripts/install-devspace-agents.sh
do
  bash -n "$script"
done

"$PYTHON" scripts/check-python-syntax.py \
  scripts/agent_mcp_runtime.py \
  scripts/codex-mcp-profile.py \
  scripts/sync-codex-mcp-config.py \
  scripts/render-codex-mcp-block.py \
  scripts/run-doctor-checks.py \
  scripts/agent-prompt-index.py \
  scripts/agent-prompt-mcp.py \
  scripts/skill_supply_chain.py \
  scripts/skill_registry.py \
  scripts/skill_intake.py \
  scripts/skill_distribution.py \
  scripts/devspace_local.py \
  scripts/agent_quality_gate.py

"$LUAC" -p desktop/hammerspoon/init.lua
