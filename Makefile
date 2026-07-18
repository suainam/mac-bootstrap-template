SHELL := /usr/bin/env bash
UV_CACHE_DIR ?= $(HOME)/.cache/uv
PYTHON ?= .venv/bin/python
LUAC ?= luac

.PHONY: help bootstrap check ci syntax-check pytest pytest-all neat-freak-ci doctor clean-cache clean-cache-aggressive cache-report \
	install-cache-agent organize-downloads install-downloads-agent \
	install-antigravity-cli install agent-sync agent-tools agent-refresh \
	skill-plan skill-fetch skill-fetch-bundle skill-ensure-bundles skill-promote skill-update skill-audit skill-diff skill-distribute skill-reconcile skill-snapshot skill-refresh skill-check system-upgrade prompt-sync prompt-index prompt-list prompt-mcp security-scan instinct-sync \
	render-configs private-sync privacy-audit privacy-audit-history export-public publish-public \
	tmux-workspace theme-switch theme-list proxy-on proxy-off cold-start obsidian-kit ghostty-font-repair \
	install-workbuddy devspace-check devspace-run devspace-doctor devspace-tunnel \
	devspace-home-push devspace-home-pull \
	quality-gate-pre-commit quality-gate-pre-push quality-gate-doctor \
	devspace-install-agent devspace-unload-agent devspace-status devspace-logs devspace-restart \
	llm-wiki-install llm-wiki-build llm-wiki-mcp-build llm-wiki-doctor \
	imgup-install imgup \
	colima-start colima-stop colima-status colima-doctor \
	claude-daemon-install claude-daemon-status claude-daemon-logs claude-daemon-unload \
	maxfiles-limit-install maxfiles-limit-status maxfiles-limit-uninstall

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "── Common ──"
	@echo "  bootstrap              Full bootstrap on this machine"
	@echo "  check                  Syntax + doctor + tests"
	@echo "  ci                     Public CI: syntax + pytest + privacy + skill + docs gates"
	@echo "  syntax-check          Shell, Python, and Lua syntax checks"
	@echo "  pytest                Run the Python test suite"
	@echo "  neat-freak-ci         Check changed operational files have public docs"
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
	@echo "  skill-fetch            Fetch one non-bundle external skill: SOURCE=id SKILL=name"
	@echo "  skill-fetch-bundle     Fetch one external bundle: SOURCE=id"
	@echo "  skill-ensure-bundles   Fetch missing enabled bundles before distribution"
	@echo "  skill-promote          Promote a staged bundle: SOURCE=id"
	@echo "  skill-update           Fetch + safely promote bundle updates: SOURCE=id"
	@echo "  skill-audit            Audit one quarantined skill: SOURCE=id SKILL=name"
	@echo "  skill-diff             Show one quarantined skill diff/hash: SOURCE=id SKILL=name"
	@echo "  skill-distribute       Wire approved managed skills into agents/projects"
	@echo "  skill-reconcile        Dry-run stale skill cleanup; APPLY=1 to prune symlinks/copies"
	@echo "  skill-snapshot         Snapshot current global/project skill views"
	@echo "  skill-refresh          Validate + wire managed skills"
	@echo "  skill-check            Validate skill registry and local skill sources"
	@echo "  system-upgrade         Interactive brew update/upgrade + safe skill refresh"
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
	@echo "  colima-start           Start isolated local Docker runtime"
	@echo "  colima-stop            Stop local Docker runtime"
	@echo "  colima-status          Show local Docker runtime status"
	@echo "  colima-doctor          Verify proxy, Docker, and log rotation"
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
	@echo "── System Limits ──"
	@echo "  maxfiles-limit-install   Install LaunchDaemon raising launchd maxfiles (sudo)"
	@echo "  maxfiles-limit-status    Show maxfiles daemon + current limit"
	@echo "  maxfiles-limit-uninstall Remove maxfiles LaunchDaemon (sudo)"
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
	$(MAKE) syntax-check
	$(MAKE) skill-check
	./scripts/privacy-audit.sh
	./scripts/doctor.sh --strict
	$(MAKE) pytest-all

ci:
	$(MAKE) syntax-check
	$(MAKE) pytest
	$(MAKE) privacy-audit
	$(MAKE) skill-check
	$(MAKE) neat-freak-ci

syntax-check:
	PYTHON="$(PYTHON)" LUAC="$(LUAC)" bash scripts/syntax-check.sh

pytest:
	mkdir -p "$(UV_CACHE_DIR)"
	if .venv/bin/python -c 'import pytest_cov' >/dev/null 2>&1; then \
		.venv/bin/python -m pytest tests/ -q -m 'not machine' --cov --cov-report=term-missing; \
	else \
		.venv/bin/python -m pytest tests/ -q -m 'not machine'; \
	fi

pytest-all:
	mkdir -p "$(UV_CACHE_DIR)"
	if .venv/bin/python -c 'import pytest_cov' >/dev/null 2>&1; then \
		.venv/bin/python -m pytest tests/ -q --cov --cov-report=term-missing; \
	else \
		.venv/bin/python -m pytest tests/ -q; \
	fi

neat-freak-ci:
	bash scripts/neat-freak-ci.sh

doctor:
	./scripts/doctor.sh

colima-start:
	./scripts/colima-local.sh start

colima-stop:
	./scripts/colima-local.sh stop

colima-status:
	./scripts/colima-local.sh status

colima-doctor:
	./scripts/colima-local.sh doctor

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

skill-fetch-bundle:
	@test -n "$(SOURCE)" || (echo "Usage: make skill-fetch-bundle SOURCE=bundle-id" >&2; exit 2)
	$(PYTHON) scripts/skill_supply_chain.py fetch-bundle --source "$(SOURCE)"

skill-ensure-bundles:
	$(PYTHON) scripts/skill_supply_chain.py ensure-bundles

skill-promote:
	@test -n "$(SOURCE)" || (echo "Usage: make skill-promote SOURCE=bundle-id" >&2; exit 2)
	$(PYTHON) scripts/skill_supply_chain.py promote --source "$(SOURCE)"

skill-update:
	$(PYTHON) scripts/skill_supply_chain.py update-bundles --source "$(or $(SOURCE),mattpocock-skills)"

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

skill-refresh: skill-check skill-ensure-bundles skill-distribute

system-upgrade:
	./scripts/system-upgrade.sh

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

# ── System maxfiles limit (survives reboot) ─────────────────
# launchd's default global soft limit (256) is too low for tools like
# codex/context-mode that fan out many fds; this raises it at every boot.
maxfiles-limit-install:
	sudo cp "$(CURDIR)/launchd/io.local.mac-bootstrap.maxfiles.plist" /Library/LaunchDaemons/io.local.mac-bootstrap.maxfiles.plist
	sudo chown root:wheel /Library/LaunchDaemons/io.local.mac-bootstrap.maxfiles.plist
	sudo chmod 644 /Library/LaunchDaemons/io.local.mac-bootstrap.maxfiles.plist
	sudo launchctl bootout system/io.local.mac-bootstrap.maxfiles 2>/dev/null || true
	sudo launchctl bootstrap system /Library/LaunchDaemons/io.local.mac-bootstrap.maxfiles.plist
	@echo "=== maxfiles daemon installed. Effective now and on every future boot. ==="
	launchctl limit maxfiles

maxfiles-limit-status:
	@echo "=== maxfiles daemon ==="
	sudo launchctl print system/io.local.mac-bootstrap.maxfiles 2>&1 | head -20
	@echo "--- current limit ---"
	launchctl limit maxfiles

maxfiles-limit-uninstall:
	sudo launchctl bootout system/io.local.mac-bootstrap.maxfiles 2>/dev/null || true
	sudo rm -f /Library/LaunchDaemons/io.local.mac-bootstrap.maxfiles.plist
	@echo "=== maxfiles daemon uninstalled ==="

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
