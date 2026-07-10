SHELL := /usr/bin/env bash
UV_CACHE_DIR ?= $(HOME)/.cache/uv
PYTHON ?= .venv/bin/python

.PHONY: help bootstrap check doctor clean-cache clean-cache-aggressive cache-report \
	install-cache-agent organize-downloads install-downloads-agent \
	install-antigravity-cli install agent-sync agent-tools agent-refresh \
	skill-plan skill-fetch skill-audit skill-diff skill-distribute skill-reconcile skill-snapshot skill-refresh skill-check prompt-sync prompt-index prompt-list prompt-mcp security-scan instinct-sync \
	render-configs private-sync privacy-audit privacy-audit-history export-public publish-public \
	tmux-workspace theme-switch theme-list proxy-on proxy-off cold-start obsidian-kit ghostty-font-repair \
	install-workbuddy devspace-check devspace-run devspace-doctor devspace-tunnel \
	devspace-home-push devspace-home-pull \
	quality-gate-pre-commit quality-gate-pre-push quality-gate-doctor \
	devspace-install-agent devspace-unload-agent devspace-status devspace-logs devspace-restart \
	llm-wiki-install llm-wiki-build llm-wiki-mcp-build llm-wiki-doctor \
	imgup-install imgup

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "── Common ──"
	@echo "  bootstrap              Full bootstrap on this machine"
	@echo "  check                  Syntax + doctor + tests"
	@echo "  doctor                 Machine health check"
	@echo "  doctor-agent           Agent tooling health check"
	@echo "  privacy-audit          Redacted privacy scan"
	@echo "  proxy-on               Configure npm + git to use the shell proxy values"
	@echo "  proxy-off              Clear npm + git proxy settings"
	@echo "  ssh-install            Deploy SSH config, keys, and helper symlinks"
	@echo "  ssh-verify             Verify SSH deploy, permissions, and ssh -G resolution"
	@echo "  ssh-key-generate       Create private/shell/ssh_keys/NAME and optional host snippet"
	@echo "  ssh-key-import         Import existing key into private/shell/ssh_keys/NAME"
	@echo "  ssh-key-import-stdin   Read pasted key from stdin into private/shell/ssh_keys/NAME"
	@echo "  tmux-workspace         Start or attach the ai-work tmux workspace"
	@echo "  obsidian-kit           Install reusable Obsidian vault kit: VAULT=/path/to/vault"
	@echo "  ghostty-font-repair    Re-register existing Liga SFMono Nerd Font files"
	@echo ""
	@echo "── Bootstrap ──"
	@echo "  install / bootstrap    Full install (Homebrew + shell + agent tooling)"
	@echo "  cold-start             Install Clash Verge proxy (first step on fresh Mac)"
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
	@echo "  agent-sync             Sync managed skills + prompt libraries"
	@echo "  agent-refresh          Full sync + full agent reconfigure"
	@echo "  skill-plan             Summarize skill registry and targets"
	@echo "  skill-fetch            Fetch one external skill: SOURCE=id SKILL=name"
	@echo "  skill-audit            Audit one quarantined skill: SOURCE=id SKILL=name"
	@echo "  skill-diff             Show one quarantined skill diff/hash: SOURCE=id SKILL=name"
	@echo "  skill-distribute       Wire approved managed skills into agents/projects"
	@echo "  skill-reconcile        Dry-run stale skill cleanup; APPLY=1 to prune symlinks/copies"
	@echo "  skill-snapshot         Snapshot current global/project skill views"
	@echo "  skill-refresh          Validate + wire managed skills"
	@echo "  skill-check            Validate skill registry and local skill sources"
	@echo "  prompt-sync            Sync prompt libraries + rebuild prompt index"
	@echo "  prompt-index           Rebuild prompt index from local prompt upstreams"
	@echo "  prompt-list            List indexed prompts: Q=query"
	@echo "  prompt-mcp             Run prompt-library MCP stdio server"
	@echo "  security-scan          Security scan + fix"
	@echo "  instinct-sync          Sync instinct files"
	@echo "  devspace-check         Validate local DevSpace config + prerequisites"
	@echo "  devspace-run           Start local DevSpace in foreground"
	@echo "  devspace-doctor        Probe local DevSpace /mcp and classify failures"
	@echo "  devspace-tunnel        Run configured Cloudflare Tunnel in foreground"
	@echo "  devspace-home-push     Mirror private DevSpace home files into ~/.devspace"
	@echo "  devspace-home-pull     Pull ~/.devspace files into private/agent mirror"
	@echo "  quality-gate-pre-commit Run the fast quality gate plan"
	@echo "  quality-gate-pre-push   Run the heavy quality gate plan"
	@echo "  quality-gate-doctor     Print quality gate plan and health inputs"
	@echo "  devspace-install-agent Install and start DevSpace LaunchAgents"
	@echo "  devspace-unload-agent  Stop and remove DevSpace LaunchAgents"
	@echo "  devspace-status        Show DevSpace LaunchAgent status and local health"
	@echo "  devspace-logs          Tail DevSpace LaunchAgent logs"
	@echo "  devspace-restart       Restart DevSpace LaunchAgents"
	@echo "  llm-wiki-install       Run official llm_wiki npm install in local checkout"
	@echo "  llm-wiki-build         Run official llm_wiki desktop build"
	@echo "  llm-wiki-mcp-build     Build llm_wiki bundled MCP server"
	@echo "  llm-wiki-doctor        Check llm_wiki checkout and prerequisites"
	@echo ""
	@echo "── Tmux ──"
	@echo "  tmux-workspace         Start or attach the ai-work tmux workspace"
	@echo "  theme-switch          Switch tmux + Ghostty theme: THEME=catppuccin-mocha|gruvbox-dark"
	@echo "  theme-list            List supported terminal themes"
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
	@echo ""
	@echo "── ImgBed ──"
	@echo "  imgup                  Upload images to CloudFlare-ImgBed (alias for imgup-install)"
	@echo "  imgup-install          Install imgup CLI symlink + validate config"

bootstrap install:
	./install.sh --yes --with-vim --with-neovim --cleanup
	./scripts/install-agent-tooling.sh --configure
	$(PYTHON) scripts/skill_supply_chain.py distribute

check:
	bash -n install.sh
	bash -n scripts/brew-bundle.sh
	bash -n scripts/configure-proxies.sh
	bash -n scripts/clear-proxies.sh
	bash -n scripts/clean-cache.sh
	bash -n scripts/cache-report.sh
	bash -n scripts/install-cache-cleanup-agent.sh
	bash -n scripts/organize-downloads.sh
	bash -n scripts/install-downloads-organizer-agent.sh
	bash -n scripts/install-antigravity-cli.sh
	bash -n scripts/doctor.sh
	bash -n scripts/install-agent-tooling.sh
	bash -n scripts/install-llm-wiki.sh
	bash -n scripts/install-npm-global-packages.sh
	bash -n scripts/lib/proxy-common.sh
	bash -n scripts/lib/agent-shared.sh
	bash -n scripts/lib/agent-manifest.sh
	bash -n scripts/lib/agent-mcp.sh
	bash -n scripts/lib/agent-configure.sh
	bash -n scripts/lib/skill-wiring.sh
	$(PYTHON) scripts/check-python-syntax.py scripts/sync-codex-mcp-config.py scripts/render-codex-mcp-block.py scripts/run-doctor-checks.py scripts/agent-prompt-index.py scripts/agent-prompt-mcp.py scripts/skill_supply_chain.py scripts/devspace_local.py scripts/agent_quality_gate.py
	$(PYTHON) scripts/skill_supply_chain.py check
	bash -n scripts/sync-private-overlay.sh
	bash -n scripts/privacy-audit.sh
	bash -n scripts/export-public-template.sh
	bash -n scripts/publish-public-template.sh
	bash -n scripts/new-project.sh
	bash -n scripts/ssh-manage.sh
	bash -n scripts/sync-agent-prompts.sh
	bash -n scripts/agent-prompt.sh
	bash -n scripts/agent-prompt-mcp.sh
	bash -n scripts/agent-doctor.sh
	bash -n editors/vscode/install-extensions.sh
	bash -n editors/vim/install.sh
	bash -n editors/vim/switch-theme.sh
	bash -n editors/neovim/install.sh
	bash -n editors/obsidian/install.sh
	bash -n multiplexer/tmux/install.sh
	bash -n multiplexer/tmux/switch-theme.sh
	bash -n terminals/ghostty/install.sh
	bash -n terminals/ghostty/repair-fonts.sh
	bash -n terminals/iterm2/install.sh
	bash -n terminals/iterm2/switch-theme.sh
	bash -n desktop/hammerspoon/install.sh
	luac -p desktop/hammerspoon/init.lua
	bash -n scripts/install-imgup.sh
	bash -n scripts/imgup.sh
	bash -n scripts/claude-daemon-tmux.sh
	bash -n scripts/tmux-workspace.sh
	bash -n scripts/switch-terminal-theme.sh
	bash -n scripts/agent-quality-gate.sh
	bash -n scripts/neat-freak-gate.sh
	bash -n scripts/knowledge-record-gate.sh
	bash -n scripts/devspace-local.sh
	bash -n scripts/devspace-supervisor.sh
	bash -n scripts/devspace-tunnel-supervisor.sh
	bash -n scripts/install-devspace-agents.sh
	./scripts/privacy-audit.sh
	./scripts/doctor.sh --strict
	mkdir -p "$(UV_CACHE_DIR)"
	if .venv/bin/python -c 'import pytest_cov' >/dev/null 2>&1; then \
		.venv/bin/python -m pytest tests/ -q --cov --cov-report=term-missing; \
	else \
		.venv/bin/python -m pytest tests/ -q; \
	fi

doctor:
	./scripts/doctor.sh

devspace-check:
	./scripts/devspace-local.sh check

devspace-run:
	./scripts/devspace-local.sh run

devspace-doctor:
	./scripts/devspace-local.sh doctor

devspace-tunnel:
	./scripts/devspace-local.sh tunnel-run

devspace-home-push:
	./scripts/devspace-local.sh home-push

devspace-home-pull:
	./scripts/devspace-local.sh home-pull

quality-gate-pre-commit:
	./scripts/agent-quality-gate.sh pre-commit

quality-gate-pre-push:
	./scripts/agent-quality-gate.sh pre-push

quality-gate-doctor:
	./scripts/agent-quality-gate.sh doctor

devspace-install-agent:
	./scripts/install-devspace-agents.sh install

devspace-unload-agent:
	./scripts/install-devspace-agents.sh unload

devspace-status:
	./scripts/install-devspace-agents.sh status

devspace-logs:
	./scripts/install-devspace-agents.sh logs

devspace-restart:
	./scripts/install-devspace-agents.sh restart

proxy-on:
	./scripts/configure-proxies.sh

proxy-off:
	./scripts/clear-proxies.sh

ssh-install:
	./scripts/ssh-manage.sh install

ssh-verify:
	./scripts/ssh-manage.sh verify

ssh-key-generate:
	@test -n "$(NAME)" || (echo "Usage: make ssh-key-generate NAME=id_ed25519_example TYPE=ed25519 [HOST=alias HOSTNAME=host USER=user PORT=22]" >&2; exit 2)
	./scripts/ssh-manage.sh add-key --name "$(NAME)" --generate --type "$(or $(TYPE),ed25519)" $(if $(HOST),--host "$(HOST)" --hostname "$(HOSTNAME)" --user "$(USER)" --port "$(or $(PORT),22)",)

ssh-key-import:
	@test -n "$(NAME)" || (echo "Usage: make ssh-key-import NAME=id_example SRC=/path/to/key [HOST=alias HOSTNAME=host USER=user PORT=22]" >&2; exit 2)
	@test -n "$(SRC)" || (echo "Usage: make ssh-key-import NAME=id_example SRC=/path/to/key [HOST=alias HOSTNAME=host USER=user PORT=22]" >&2; exit 2)
	./scripts/ssh-manage.sh add-key --name "$(NAME)" --import "$(SRC)" $(if $(HOST),--host "$(HOST)" --hostname "$(HOSTNAME)" --user "$(USER)" --port "$(or $(PORT),22)",)

ssh-key-import-stdin:
	@test -n "$(NAME)" || (echo "Usage: cat key | make ssh-key-import-stdin NAME=id_example [HOST=alias HOSTNAME=host USER=user PORT=22]" >&2; exit 2)
	./scripts/ssh-manage.sh add-key --name "$(NAME)" --stdin $(if $(HOST),--host "$(HOST)" --hostname "$(HOSTNAME)" --user "$(USER)" --port "$(or $(PORT),22)",)

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

agent-sync: skill-refresh prompt-sync

agent-tools:
	./scripts/install-agent-tooling.sh --configure

agent-refresh: agent-sync agent-tools

skill-plan:
	$(PYTHON) scripts/skill_supply_chain.py plan

skill-fetch:
	@test -n "$(SOURCE)" || (echo "Usage: make skill-fetch SOURCE=id SKILL=name" >&2; exit 2)
	@test -n "$(SKILL)" || (echo "Usage: make skill-fetch SOURCE=id SKILL=name" >&2; exit 2)
	$(PYTHON) scripts/skill_supply_chain.py fetch --source "$(SOURCE)" --skill "$(SKILL)"

skill-audit:
	@test -n "$(SOURCE)" || (echo "Usage: make skill-audit SOURCE=id SKILL=name" >&2; exit 2)
	@test -n "$(SKILL)" || (echo "Usage: make skill-audit SOURCE=id SKILL=name" >&2; exit 2)
	$(PYTHON) scripts/skill_supply_chain.py audit --source "$(SOURCE)" --skill "$(SKILL)"

skill-diff:
	@test -n "$(SOURCE)" || (echo "Usage: make skill-diff SOURCE=id SKILL=name" >&2; exit 2)
	@test -n "$(SKILL)" || (echo "Usage: make skill-diff SOURCE=id SKILL=name" >&2; exit 2)
	$(PYTHON) scripts/skill_supply_chain.py diff --source "$(SOURCE)" --skill "$(SKILL)"

skill-distribute:
	$(PYTHON) scripts/skill_supply_chain.py distribute

skill-reconcile:
	$(PYTHON) scripts/skill_supply_chain.py reconcile $(if $(APPLY),--apply,)

skill-snapshot:
	$(PYTHON) scripts/skill_supply_chain.py snapshot --label "$${LABEL:-manual}"

skill-refresh: skill-check skill-distribute

skill-check:
	$(PYTHON) scripts/skill_supply_chain.py check

prompt-sync:
	./scripts/sync-agent-prompts.sh

prompt-index:
	$(PYTHON) scripts/agent-prompt-index.py build

prompt-list:
	./scripts/agent-prompt.sh list "$(Q)"

prompt-mcp:
	./scripts/agent-prompt-mcp.sh

obsidian-kit:
	@test -n "$(VAULT)" || (echo "Usage: make obsidian-kit VAULT=/path/to/vault" >&2; exit 2)
	./editors/obsidian/install.sh "$(VAULT)"

ghostty-font-repair:
	./terminals/ghostty/repair-fonts.sh

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

npm-packages:
	./scripts/install-npm-global-packages.sh --yes

npm-packages-upgrade:
	./scripts/install-npm-global-packages.sh --yes --upgrade

llm-wiki-install:
	./scripts/install-llm-wiki.sh install

llm-wiki-build:
	./scripts/install-llm-wiki.sh build

llm-wiki-mcp-build:
	./scripts/install-llm-wiki.sh mcp-build

llm-wiki-doctor:
	./scripts/install-llm-wiki.sh doctor

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

theme-switch:
	@test -n "$(THEME)" || (echo "Usage: make theme-switch THEME=catppuccin-mocha|gruvbox-dark" >&2; exit 2)
	./scripts/switch-terminal-theme.sh "$(THEME)"

theme-list:
	@echo "catppuccin-mocha"
	@echo "gruvbox-dark"

# ── WorkBuddy ────────────────────────────────────────────────────────
install-workbuddy:
	./scripts/install-workbuddy.sh

imgup-install:
	./scripts/install-imgup.sh

imgup: imgup-install

# ── Cold Start (Proxy Bootstrap) ────────────────────────────────────
cold-start:
	./scripts/install-clash.sh
cold-start-dry:
	./scripts/install-clash.sh --dry-run
