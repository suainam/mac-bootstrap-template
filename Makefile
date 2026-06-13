SHELL := /usr/bin/env bash

.PHONY: help bootstrap check doctor clean-cache clean-cache-aggressive cache-report \
	install-cache-agent organize-downloads install-downloads-agent \
	install-antigravity-cli install agent-sync agent-tools security-scan instinct-sync \
	render-configs private-sync privacy-audit privacy-audit-history export-public publish-public \
	tmux-workspace \
	reverse-tunnel-install reverse-tunnel-unload reverse-tunnel-status reverse-tunnel-logs

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "── Bootstrap ──"
	@echo "  install / bootstrap    Full install (Homebrew + shell + agent tooling)"
	@echo "  check                  Syntax-check all scripts + run doctor"
	@echo "  doctor                 System health check"
	@echo "  doctor-agent           Agent tooling health check"
	@echo ""
	@echo "── Cleanup ──"
	@echo "  clean-cache            Clean Homebrew/Library/LaTeX caches"
	@echo "  clean-cache-aggressive More aggressive cache cleanup"
	@echo "  cache-report           Show cache sizes"
	@echo ""
	@echo "── Agent ──"
	@echo "  agent-tools            Install/configure agent tooling"
	@echo "  agent-sync             Sync agent upstreams"
	@echo "  security-scan          Security scan + fix"
	@echo "  instinct-sync          Sync instinct files"
	@echo ""
	@echo "── Tmux ──"
	@echo "  tmux-workspace         Start or attach the ai-work tmux workspace"
	@echo ""
	@echo "── SSH Reverse Tunnel ──"
	@echo "  reverse-tunnel-install Install & start SSH reverse tunnel (15721 → bastion)"
	@echo "  reverse-tunnel-unload  Stop SSH reverse tunnel"
	@echo "  reverse-tunnel-status  Show tunnel daemon status"
	@echo "  reverse-tunnel-logs    Tail tunnel logs"
	@echo ""
	@echo "── Claude Daemon (tmux) ──"
	@echo "  claude-daemon-install    Install tmux-based daemon"
	@echo "  claude-daemon-unload     Stop daemon services"
	@echo "  claude-daemon-status     Show daemon status"
	@echo "  claude-daemon-logs       Show daemon logs"
	@echo ""
	@echo "── Config ──"
	@echo "  render-configs         Render config templates"
	@echo "  private-sync           Sync private overlay"
	@echo "  privacy-audit          Scan for secrets"
	@echo "  privacy-audit-history  Scan with git history"
	@echo "  export-public DEST=…   Export public template"
	@echo "  publish-public         Publish public template"
	@echo ""
	@echo "── Other ──"
	@echo "  pi-packages            Install Pi packages"
	@echo "  pm-detect              Detect package manager"
	@echo "  pm-set                 Set global package manager"
	@echo "  mcp-profiles           Setup MCP profiles"
	@echo "  hook-matchers          Add hook matchers"

bootstrap install:
	./install.sh --yes --with-vim --cleanup
	./scripts/install-agent-tooling.sh --configure

check:
	bash -n install.sh
	bash -n scripts/brew-bundle.sh
	bash -n scripts/configure-proxies.sh
	bash -n scripts/clean-cache.sh
	bash -n scripts/cache-report.sh
	bash -n scripts/install-cache-cleanup-agent.sh
	bash -n scripts/organize-downloads.sh
	bash -n scripts/install-downloads-organizer-agent.sh
	bash -n scripts/install-antigravity-cli.sh
	bash -n scripts/doctor.sh
	bash -n scripts/install-agent-tooling.sh
	bash -n scripts/sync-private-overlay.sh
	bash -n scripts/privacy-audit.sh
	bash -n scripts/export-public-template.sh
	bash -n scripts/publish-public-template.sh
	bash -n scripts/new-project.sh
	bash -n scripts/sync-agent-upstreams.sh
	bash -n scripts/agent-doctor.sh
	bash -n vscode/install-extensions.sh
	bash -n vim/install.sh
	bash -n vim/switch-theme.sh
	bash -n tmux/install.sh
	bash -n tmux/switch-theme.sh
	bash -n iterm2/install.sh
	bash -n iterm2/switch-theme.sh
	bash -n hammerspoon/install.sh
	luac -p hammerspoon/init.lua
	bash -n scripts/claude-daemon-tmux.sh
	bash -n scripts/tmux-workspace.sh
	bash -n scripts/ssh-reverse-tunnel.sh
	./scripts/privacy-audit.sh
	./scripts/doctor.sh --strict

doctor:
	./scripts/doctor.sh

doctor-agent:
	./scripts/agent-doctor.sh

security-scan:
	./scripts/agent-doctor.sh --fix

clean-cache:
	./scripts/clean-cache.sh

clean-cache-aggressive:
	./scripts/clean-cache.sh --aggressive

cache-report:
	./scripts/cache-report.sh

install-cache-agent:
	./scripts/install-cache-cleanup-agent.sh

organize-downloads:
	./scripts/organize-downloads.sh

install-downloads-agent:
	./scripts/install-downloads-organizer-agent.sh

install-antigravity-cli:
	./scripts/install-antigravity-cli.sh

agent-sync:
	./scripts/sync-agent-upstreams.sh

agent-tools:
	./scripts/install-agent-tooling.sh --configure

render-configs:
	./scripts/render-configs.sh

private-sync:
	./scripts/sync-private-overlay.sh

privacy-audit:
	./scripts/privacy-audit.sh

privacy-audit-history:
	./scripts/privacy-audit.sh --history

export-public:
	@test -n "$(DEST)" || (echo "Usage: make export-public DEST=/path/to/public-template" >&2; exit 2)
	./scripts/export-public-template.sh --dest "$(DEST)"

publish-public:
	@test -n "$(PUBLIC_REPO)$(PUBLIC_REMOTE)$(MAC_BOOTSTRAP_PUBLIC_REPO)$(MAC_BOOTSTRAP_PUBLIC_REMOTE)" || (echo "Usage: PUBLIC_REPO=owner/repo make publish-public" >&2; exit 2)
	./scripts/publish-public-template.sh

pi-packages:
	./scripts/install-pi-packages.sh --yes

pm-detect:
	@./scripts/detect-package-manager.sh

pm-set:
	@./scripts/detect-package-manager.sh --set-global $(filter-out $@,$(MAKECMDGOALS))

mcp-profiles:
	./scripts/setup-mcp-profiles.sh

hook-matchers:
	./scripts/add-hook-matchers.sh

# ── Claude Code Daemon ─────────────────────────────────────
claude-daemon-install:
	@mkdir -p "$(HOME)/Library/LaunchAgents"
	for plist in launchd/io.local.mac-bootstrap.claude-daemon.plist; do \
		name="$$(basename "$$plist")"; \
		cp "$$plist" "$(HOME)/Library/LaunchAgents/$$name"; \
		sed -i '' "s|{{BOOTSTRAP}}|$(CURDIR)|g" "$(HOME)/Library/LaunchAgents/$$name"; \
		echo "  $$name -> ~/Library/LaunchAgents/"; \
	done
	launchctl bootstrap gui/$$(id -u) "$(HOME)/Library/LaunchAgents/io.local.mac-bootstrap.claude-daemon.plist" 2>/dev/null || \
		launchctl enable gui/$$(id -u)/io.local.mac-bootstrap.claude-daemon
	@echo "=== Claude daemon installed. Logs: ~/Library/Logs/claude-daemon/ ==="

claude-daemon-status:
	@echo "=== claude-daemon ==="
	launchctl print gui/$$(id -u)/io.local.mac-bootstrap.claude-daemon 2>&1 | head -20

claude-daemon-logs:
	@echo "=== Tmux daemon ==="
	tail -20 "$(HOME)/Library/Logs/claude-daemon/tmux.log" 2>/dev/null || echo "(no tmux.log)"

claude-daemon-unload:
	launchctl bootout gui/$$(id -u) "$(HOME)/Library/LaunchAgents/io.local.mac-bootstrap.claude-daemon.plist" 2>/dev/null || true
	@echo "=== Claude daemon unloaded ==="

# ── Tmux Workspace ───────────────────────────────────────────────
tmux-workspace:
	"$(HOME)/.local/bin/tmux-workspace.sh"

# ── SSH Reverse Tunnel ─────────────────────────────────────────────
# Exposes local cc-switch proxy (127.0.0.1:15721) on bastion localhost.
# Requires an active ControlMaster socket for dsliam (interactive login first).
# On bastion: export ANTHROPIC_BASE_URL=http://127.0.0.1:15721
reverse-tunnel-install:
	@mkdir -p "$(HOME)/Library/LaunchAgents"
	cp launchd/io.local.mac-bootstrap.ssh-reverse-tunnel.plist "$(HOME)/Library/LaunchAgents/"
	sed -i '' "s|{{BOOTSTRAP}}|$(CURDIR)|g" "$(HOME)/Library/LaunchAgents/io.local.mac-bootstrap.ssh-reverse-tunnel.plist"
	launchctl bootstrap gui/$$(id -u) "$(HOME)/Library/LaunchAgents/io.local.mac-bootstrap.ssh-reverse-tunnel.plist" 2>/dev/null || \
		launchctl enable gui/$$(id -u)/io.local.mac-bootstrap.ssh-reverse-tunnel
	@echo "=== ssh-reverse-tunnel installed. Log: ~/Library/Logs/claude-daemon/ssh-reverse-tunnel.log ==="
	@echo "=== On bastion: export ANTHROPIC_BASE_URL=http://127.0.0.1:15721 ==="

reverse-tunnel-unload:
	launchctl bootout gui/$$(id -u) "$(HOME)/Library/LaunchAgents/io.local.mac-bootstrap.ssh-reverse-tunnel.plist" 2>/dev/null || true
	@echo "=== ssh-reverse-tunnel unloaded ==="

reverse-tunnel-status:
	launchctl print gui/$$(id -u)/io.local.mac-bootstrap.ssh-reverse-tunnel 2>&1 | head -20 || echo "(not loaded)"

reverse-tunnel-logs:
	tail -40 "$(HOME)/Library/Logs/claude-daemon/ssh-reverse-tunnel.log" 2>/dev/null || echo "(no log yet)"
