SHELL := /usr/bin/env bash
UV_CACHE_DIR ?= $(HOME)/.cache/uv
PYTHON ?= .venv/bin/python
PYTEST_PARALLEL_WORKERS ?= 4
# Incremental docs-check scope: uncommitted docs by default; DOCS_BASE=origin/main
# widens it to a branch diff.
DOCS_BASE ?= HEAD
PYTEST_PARALLEL_ARGS ?= -n $(PYTEST_PARALLEL_WORKERS) --dist loadfile
LUAC ?= luac
GIT_HOOK_REPO ?= .
GIT_HOOK_REGISTRY ?= agent/runtime/registry.jsonc
GIT_HOOK_APPROVALS ?=
GIT_HOOK_PYTHON ?= $(shell command -v python3)
DISPATCH_SOURCE ?= $(HOME)/.local/src/Dispatch

.PHONY: help bootstrap check check-parallel repo-check repo-check-serial repo-check-parallel machine-check ci syntax-check pytest pytest-machine pytest-parallel pytest-all neat-freak-ci doctor clean-cache clean-cache-aggressive cache-report \
	install-cache-agent organize-downloads install-downloads-agent install-maintenance-agents unload-maintenance-agents system-patrol \
	install-antigravity-cli install agent-sync agent-tools agent-refresh agent-rules-audit \
	skill-plan skill-fetch skill-fetch-bundle skill-ensure-bundles skill-promote skill-update skill-audit skill-diff skill-distribute skill-reconcile skill-snapshot skill-refresh skill-check system-upgrade prompt-sync prompt-index prompt-list prompt-mcp security-scan \
	package-migrate \
 	omp-extensions dispatch-install dispatch-upgrade dispatch-status dispatch-doctor dispatch-uninstall \
	render-configs private-sync privacy-audit privacy-audit-history export-public publish-public \
	theme-switch theme-list proxy-on proxy-off cold-start obsidian-kit ghostty-font-repair \
	external-tools devspace-check devspace-run devspace-doctor devspace-tunnel \
	devspace-home-push devspace-home-pull \
	quality-gate-pre-commit quality-gate-pre-push quality-gate-doctor \
	quality-gate-hook-inventory quality-gate-hook-install quality-gate-hook-uninstall quality-gate-hook-doctor \
	devspace-install-agent devspace-unload-agent devspace-status devspace-logs devspace-restart \
	imgup-install imgup \
	colima-start colima-stop colima-status colima-doctor \
	claude-daemon-install claude-daemon-status claude-daemon-logs claude-daemon-unload \
	maxfiles-limit-install maxfiles-limit-status maxfiles-limit-uninstall cleanup-services \
	net-tune net-tune-apply net-tune-save net-tune-auto net-tune-list net-tune-status net-tune-restore \
	ssh-install ssh-verify ssh-smoke

HELP_AWK ?= scripts/make_help.awk

help:
	@echo "Usage: make <target>"
	@awk -f "$(HELP_AWK)" "$(firstword $(MAKEFILE_LIST))"

## 1.1 Common | bootstrap | Full bootstrap on this machine
## 2.1 Bootstrap | install / bootstrap | Full install (Homebrew + shell + agent tooling)
bootstrap install:
	./install.sh --yes --with-vim --with-neovim --cleanup
	./scripts/install-agent-tooling.sh --configure
	./scripts/install-omp-extensions.sh
	$(PYTHON) scripts/skill_supply_chain.py distribute

docs-check:
	@files="$${DOCS_PATHS:-$$(git diff --name-only --diff-filter=ACMR $(DOCS_BASE) -- '*.md' '*.mdx' 2>/dev/null)}"; \
	if [ -z "$$files" ]; then echo "docs-check: no changed docs"; exit 0; fi; \
	"$(PYTHON)" scripts/check_docs.py $$files

docs-check-all:
	@"$(PYTHON)" scripts/check_docs.py .

## 1.4 Common | repo-check | Repository-only grouped syntax, privacy, skills, and tests
repo-check: docs-check
	+$(MAKE) syntax-check skill-check privacy-audit pytest-parallel

## 1.5 Common | repo-check-serial | Repository-only serial checks for debugging
repo-check-serial:
	$(MAKE) syntax-check
	$(MAKE) skill-check
	./scripts/privacy-audit.sh
	$(MAKE) pytest

repo-check-parallel: repo-check

## 1.6 Common | machine-check | Strict machine health check
machine-check:
	./scripts/doctor.sh --strict
	$(MAKE) pytest-machine

## 1.2 Common | check | Repository checks + strict machine doctor
## 2.3 Bootstrap | check | Syntax-check all scripts + run doctor
check: check-parallel

## 1.3 Common | check-parallel | Repository + machine checks with grouped xdist
check-parallel:
	+$(MAKE) -j2 repo-check-parallel machine-check

check-serial:
	$(MAKE) repo-check-serial
	$(MAKE) machine-check

## 1.7 Common | ci | Public CI: syntax + pytest + privacy + skill + docs gates
ci:
	$(MAKE) syntax-check
	$(MAKE) pytest
	$(MAKE) privacy-audit
	$(MAKE) skill-check
	$(MAKE) neat-freak-ci

## 1.8 Common | syntax-check | Shell, Python, and Lua syntax checks
syntax-check:
	PYTHON="$(PYTHON)" LUAC="$(LUAC)" bash scripts/syntax-check.sh

## 1.9 Common | pytest | Run repository-only Python tests
pytest:
	mkdir -p "$(UV_CACHE_DIR)"
	if $(PYTHON) -c 'import pytest_cov' >/dev/null 2>&1; then \
		env -u PYTHON -u PYTHON_BIN $(PYTHON) -m pytest tests/ -q -m 'not machine' --cov --cov-report=term-missing; \
	else \
		env -u PYTHON -u PYTHON_BIN $(PYTHON) -m pytest tests/ -q -m 'not machine'; \
	fi

## 1.10 Common | pytest-machine | Run machine-dependent Python tests
pytest-machine:
	mkdir -p "$(UV_CACHE_DIR)"
	env -u PYTHON -u PYTHON_BIN $(PYTHON) -m pytest tests/ -q -m machine

pytest-parallel:
	mkdir -p "$(UV_CACHE_DIR)"
	if $(PYTHON) -c 'import pytest_cov' >/dev/null 2>&1; then \
		env -u PYTHON -u PYTHON_BIN $(PYTHON) -m pytest tests/ -q -m 'not machine' --cov --cov-report=term-missing $(PYTEST_PARALLEL_ARGS); \
	else \
		env -u PYTHON -u PYTHON_BIN $(PYTHON) -m pytest tests/ -q -m 'not machine' $(PYTEST_PARALLEL_ARGS); \
	fi

pytest-all:
	mkdir -p "$(UV_CACHE_DIR)"
	if $(PYTHON) -c 'import pytest_cov' >/dev/null 2>&1; then \
		env -u PYTHON -u PYTHON_BIN $(PYTHON) -m pytest tests/ -q --cov --cov-report=term-missing; \
	else \
		env -u PYTHON -u PYTHON_BIN $(PYTHON) -m pytest tests/ -q; \
	fi

## 1.11 Common | neat-freak-ci | Check changed operational files have public docs
neat-freak-ci:
	bash scripts/neat-freak-ci.sh

## 1.12 Common | doctor | Machine health check
## 2.4 Bootstrap | doctor | System health check
doctor:
	./scripts/doctor.sh

## 4.48 Agent | colima-start | Start isolated local Docker runtime
colima-start:
	./scripts/colima-local.sh start

## 4.49 Agent | colima-stop | Stop local Docker runtime
colima-stop:
	./scripts/colima-local.sh stop

## 4.50 Agent | colima-status | Show local Docker runtime status
colima-status:
	./scripts/colima-local.sh status

## 4.51 Agent | colima-doctor | Verify proxy, Docker, and log rotation
colima-doctor:
	./scripts/colima-local.sh doctor

## 4.30 Agent | devspace-check | Validate local DevSpace config + prerequisites
devspace-check:
	./scripts/devspace-local.sh check

## 4.31 Agent | devspace-run | Start local DevSpace in foreground
devspace-run:
	./scripts/devspace-local.sh run

## 4.32 Agent | devspace-doctor | Probe local DevSpace /mcp and classify failures
devspace-doctor:
	./scripts/devspace-local.sh doctor

## 4.33 Agent | devspace-tunnel | Run configured Cloudflare Tunnel in foreground
devspace-tunnel:
	./scripts/devspace-local.sh tunnel-run

## 4.34 Agent | devspace-home-push | Mirror private DevSpace home files into ~/.devspace
devspace-home-push:
	./scripts/devspace-local.sh home-push

## 4.35 Agent | devspace-home-pull | Pull ~/.devspace files into private/agent mirror
devspace-home-pull:
	./scripts/devspace-local.sh home-pull

## 4.36 Agent | quality-gate-pre-commit | Run the fast quality gate plan
quality-gate-pre-commit:
	./scripts/agent-quality-gate.sh pre-commit

## 4.37 Agent | quality-gate-pre-push | Run the heavy quality gate plan
quality-gate-pre-push:
	./scripts/agent-quality-gate.sh pre-push

## 4.38 Agent | quality-gate-doctor | Print legacy quality gate plan and health inputs
quality-gate-doctor:
	./scripts/agent-quality-gate.sh doctor

## 4.39 Agent | quality-gate-hook-inventory | Inventory existing Git/LFS/legacy hooks
quality-gate-hook-inventory:
	$(PYTHON) scripts/agent_git_hook_dispatcher.py --repo "$(GIT_HOOK_REPO)" inventory

## 4.40 Agent | quality-gate-hook-install | Install trusted user-level dispatcher (explicit migration only)
quality-gate-hook-install:
	$(PYTHON) scripts/agent_git_hook_dispatcher.py --repo "$(GIT_HOOK_REPO)" --python "$(GIT_HOOK_PYTHON)" install --registry "$(GIT_HOOK_REGISTRY)" $(GIT_HOOK_APPROVALS)

## 4.41 Agent | quality-gate-hook-uninstall | Restore the previous hooksPath atomically
quality-gate-hook-uninstall:
	$(PYTHON) scripts/agent_git_hook_dispatcher.py --repo "$(GIT_HOOK_REPO)" uninstall

## 4.42 Agent | quality-gate-hook-doctor | Verify trusted dispatcher, registry, hooks, and approved chains
quality-gate-hook-doctor:
	$(PYTHON) scripts/agent_git_hook_dispatcher.py --repo "$(GIT_HOOK_REPO)" doctor

## 4.43 Agent | devspace-install-agent | Install and start DevSpace LaunchAgents
devspace-install-agent:
	./scripts/install-devspace-agents.sh install

## 4.44 Agent | devspace-unload-agent | Stop and remove DevSpace LaunchAgents
devspace-unload-agent:
	./scripts/install-devspace-agents.sh unload

## 4.45 Agent | devspace-status | Show DevSpace LaunchAgent status and local health
devspace-status:
	./scripts/install-devspace-agents.sh status

## 4.46 Agent | devspace-logs | Tail DevSpace LaunchAgent logs
devspace-logs:
	./scripts/install-devspace-agents.sh logs

## 4.47 Agent | devspace-restart | Restart DevSpace LaunchAgents
devspace-restart:
	./scripts/install-devspace-agents.sh restart

## 1.17 Common | proxy-on | Configure npm + git to use the shell proxy values
proxy-on:
	./scripts/configure-proxies.sh

## 1.18 Common | proxy-off | Clear npm + git proxy settings
proxy-off:
	./scripts/clear-proxies.sh

## 1.19 Common | ssh-install | Deploy SSH config, keys, and helper symlinks
ssh-install:
	./scripts/ssh-manage.sh install

## 1.20 Common | ssh-verify | Verify SSH deploy, permissions, and ssh -G resolution
ssh-verify:
	./scripts/ssh-manage.sh verify

## 1.24 Common | ssh-smoke | Live SSH auth probe (HOST=github.com) for proxy wiring
ssh-smoke:
	./scripts/ssh-manage.sh smoke $(or $(HOST),github.com)

## 1.21 Common | ssh-key-generate | Create private/shell/ssh_keys/NAME and optional host snippet
ssh-key-generate:
	@test -n "$(NAME)" || (echo "Usage: make ssh-key-generate NAME=id_ed25519_example TYPE=ed25519 [HOST=alias HOSTNAME=host USER=user PORT=22]" >&2; exit 2)
	./scripts/ssh-manage.sh add-key --name "$(NAME)" --generate --type "$(or $(TYPE),ed25519)" $(if $(HOST),--host "$(HOST)" --hostname "$(HOSTNAME)" --user "$(USER)" --port "$(or $(PORT),22)",)

## 1.22 Common | ssh-key-import | Import existing key into private/shell/ssh_keys/NAME
ssh-key-import:
	@test -n "$(NAME)" || (echo "Usage: make ssh-key-import NAME=id_example SRC=/path/to/key [HOST=alias HOSTNAME=host USER=user PORT=22]" >&2; exit 2)
	@test -n "$(SRC)" || (echo "Usage: make ssh-key-import NAME=id_example SRC=/path/to/key [HOST=alias HOSTNAME=host USER=user PORT=22]" >&2; exit 2)
	./scripts/ssh-manage.sh add-key --name "$(NAME)" --import "$(SRC)" $(if $(HOST),--host "$(HOST)" --hostname "$(HOSTNAME)" --user "$(USER)" --port "$(or $(PORT),22)",)

## 1.23 Common | ssh-key-import-stdin | Read pasted key from stdin into private/shell/ssh_keys/NAME
ssh-key-import-stdin:
	@test -n "$(NAME)" || (echo "Usage: cat key | make ssh-key-import-stdin NAME=id_example [HOST=alias HOSTNAME=host USER=user PORT=22]" >&2; exit 2)
	./scripts/ssh-manage.sh add-key --name "$(NAME)" --stdin $(if $(HOST),--host "$(HOST)" --hostname "$(HOSTNAME)" --user "$(USER)" --port "$(or $(PORT),22)",)

## 1.13 Common | doctor-agent | Agent tooling health check
## 2.5 Bootstrap | doctor-agent | Agent tooling health check
doctor-agent:
	./scripts/agent-doctor.sh

## 1.14 Common | agent-rules-audit | Scan all AGENTS.md / CLAUDE.md for duplicate imports & drift
agent-rules-audit:
	@"$(PYTHON)" ./scripts/audit-agent-rules.py || python3 ./scripts/audit-agent-rules.py

## 4.28 Agent | security-scan | Security scan + fix
security-scan:
	./scripts/agent-doctor.sh --fix

## 3.1 Cleanup | clean-cache | Clean Homebrew/Library/LaTeX caches
clean-cache:
	./scripts/clean-cache.sh

## 3.2 Cleanup | clean-cache-aggressive | More aggressive cache cleanup
clean-cache-aggressive:
	./scripts/clean-cache.sh --aggressive

## 3.3 Cleanup | cache-report | Show cache sizes
cache-report:
	./scripts/cache-report.sh

install-cache-agent:
	./scripts/install-maintenance-agents.sh install cache-cleanup

organize-downloads:
	./scripts/organize-downloads.sh

install-downloads-agent:
	./scripts/install-maintenance-agents.sh install downloads-organizer

install-antigravity-cli:
	./scripts/install-antigravity-cli.sh

## 4.2 Agent | agent-sync | Sync managed skills + prompt libraries
agent-sync: skill-refresh prompt-sync

## 4.1 Agent | agent-tools | Install/configure agent tooling
agent-tools:
	./scripts/install-agent-tooling.sh --configure

## 4.4 Agent | omp-extensions | Install version-pinned OMP extensions
omp-extensions:
	./scripts/install-omp-extensions.sh

## 4.5 Agent | dispatch-install | Install standalone Dispatch from DISPATCH_SOURCE
dispatch-install:
	@test -x "$(DISPATCH_SOURCE)/bin/dispatchctl" || { echo "Dispatch source not found: $(DISPATCH_SOURCE)" >&2; exit 2; }
	"$(DISPATCH_SOURCE)/bin/dispatchctl" install

## 4.6 Agent | dispatch-upgrade | Upgrade standalone Dispatch from DISPATCH_SOURCE
dispatch-upgrade:
	@test -x "$(DISPATCH_SOURCE)/bin/dispatchctl" || { echo "Dispatch source not found: $(DISPATCH_SOURCE)" >&2; exit 2; }
	"$(DISPATCH_SOURCE)/bin/dispatchctl" upgrade

## 4.7 Agent | dispatch-status | Show standalone Dispatch status
dispatch-status:
	@test -x "$(DISPATCH_SOURCE)/bin/dispatchctl" || { echo "Dispatch source not found: $(DISPATCH_SOURCE)" >&2; exit 2; }
	"$(DISPATCH_SOURCE)/bin/dispatchctl" status

## 4.8 Agent | dispatch-doctor | Run standalone Dispatch doctor
dispatch-doctor:
	@test -x "$(DISPATCH_SOURCE)/bin/dispatchctl" || { echo "Dispatch source not found: $(DISPATCH_SOURCE)" >&2; exit 2; }
	"$(DISPATCH_SOURCE)/bin/dispatchctl" doctor

## 4.9 Agent | dispatch-uninstall | Uninstall standalone Dispatch (state preserved by default)
dispatch-uninstall:
	@test -x "$(DISPATCH_SOURCE)/bin/dispatchctl" || { echo "Dispatch source not found: $(DISPATCH_SOURCE)" >&2; exit 2; }
	"$(DISPATCH_SOURCE)/bin/dispatchctl" uninstall

## 4.3 Agent | agent-refresh | Full sync + full agent reconfigure
agent-refresh: agent-sync agent-tools omp-extensions

## 4.10 Agent | skill-plan | Summarize skill registry and targets
skill-plan:
	$(PYTHON) scripts/skill_supply_chain.py plan

## 4.11 Agent | skill-fetch | Fetch one non-bundle external skill: SOURCE=id SKILL=name
skill-fetch:
	@test -n "$(SOURCE)" || (echo "Usage: make skill-fetch SOURCE=id SKILL=name" >&2; exit 2)
	@test -n "$(SKILL)" || (echo "Usage: make skill-fetch SOURCE=id SKILL=name" >&2; exit 2)
	$(PYTHON) scripts/skill_supply_chain.py fetch --source "$(SOURCE)" --skill "$(SKILL)"

## 4.12 Agent | skill-fetch-bundle | Fetch one external bundle: SOURCE=id
skill-fetch-bundle:
	@test -n "$(SOURCE)" || (echo "Usage: make skill-fetch-bundle SOURCE=bundle-id" >&2; exit 2)
	$(PYTHON) scripts/skill_supply_chain.py fetch-bundle --source "$(SOURCE)"

## 4.13 Agent | skill-ensure-bundles | Fetch missing enabled bundles before distribution
skill-ensure-bundles:
	$(PYTHON) scripts/skill_supply_chain.py ensure-bundles

## 4.14 Agent | skill-promote | Promote a staged bundle: SOURCE=id
skill-promote:
	@test -n "$(SOURCE)" || (echo "Usage: make skill-promote SOURCE=bundle-id" >&2; exit 2)
	$(PYTHON) scripts/skill_supply_chain.py promote --source "$(SOURCE)"

## 4.15 Agent | skill-update | Fetch + safely promote bundle updates: SOURCE=id
skill-update:
	$(PYTHON) scripts/skill_supply_chain.py update-bundles --source "$(or $(SOURCE),mattpocock-skills)"

## 4.16 Agent | skill-audit | Audit one quarantined skill: SOURCE=id SKILL=name
skill-audit:
	@test -n "$(SOURCE)" || (echo "Usage: make skill-audit SOURCE=id SKILL=name" >&2; exit 2)
	@test -n "$(SKILL)" || (echo "Usage: make skill-audit SOURCE=id SKILL=name" >&2; exit 2)
	$(PYTHON) scripts/skill_supply_chain.py audit --source "$(SOURCE)" --skill "$(SKILL)"

## 4.17 Agent | skill-diff | Show one quarantined skill diff/hash: SOURCE=id SKILL=name
skill-diff:
	@test -n "$(SOURCE)" || (echo "Usage: make skill-diff SOURCE=id SKILL=name" >&2; exit 2)
	@test -n "$(SKILL)" || (echo "Usage: make skill-diff SOURCE=id SKILL=name" >&2; exit 2)
	$(PYTHON) scripts/skill_supply_chain.py diff --source "$(SOURCE)" --skill "$(SKILL)"

## 4.18 Agent | skill-distribute | Wire approved managed skills into agents/projects
skill-distribute:
	$(PYTHON) scripts/skill_supply_chain.py distribute

## 4.19 Agent | skill-reconcile | Dry-run stale skill cleanup; APPLY=1 to prune symlinks/copies
skill-reconcile:
	$(PYTHON) scripts/skill_supply_chain.py reconcile $(if $(APPLY),--apply,)

## 4.20 Agent | skill-snapshot | Snapshot current global/project skill views
skill-snapshot:
	$(PYTHON) scripts/skill_supply_chain.py snapshot --label "$${LABEL:-manual}"

## 4.21 Agent | skill-refresh | Validate + wire managed skills
skill-refresh: skill-check skill-ensure-bundles skill-distribute

## 4.23 Agent | system-upgrade | Interactive system + manifest-managed npm upgrade + safe skill refresh
system-upgrade:
	@test -z "$(args)" || { echo "Error: 'args' is ignored by make; use uppercase ARGS, e.g. make system-upgrade ARGS=--yes" >&2; exit 2; }
	./scripts/system-upgrade.sh $(if $(UPGRADE_ONLY),--only $(UPGRADE_ONLY),) $(ARGS)

package-migrate:
	./scripts/brew-bundle.sh migrate

## 4.22 Agent | skill-check | Validate skill registry and local skill sources
skill-check:
	$(PYTHON) scripts/skill_supply_chain.py check

## 4.24 Agent | prompt-sync | Sync prompt libraries + rebuild prompt index
prompt-sync:
	./scripts/sync-agent-prompts.sh

## 4.25 Agent | prompt-index | Rebuild prompt index from local prompt upstreams
prompt-index:
	$(PYTHON) scripts/agent-prompt-index.py build

## 4.26 Agent | prompt-list | List indexed prompts: Q=query
prompt-list:
	./scripts/agent-prompt.sh list "$(Q)"

## 4.27 Agent | prompt-mcp | Run prompt-library MCP stdio server
prompt-mcp:
	./scripts/agent-prompt-mcp.sh

## 1.26 Common | obsidian-kit | Install reusable Obsidian vault kit: VAULT=/path/to/vault
obsidian-kit:
	@test -n "$(VAULT)" || (echo "Usage: make obsidian-kit VAULT=/path/to/vault" >&2; exit 2)
	./editors/obsidian/install.sh "$(VAULT)"

## 1.27 Common | ghostty-font-repair | Re-register existing Liga SFMono Nerd Font files
ghostty-font-repair:
	./terminals/ghostty/repair-fonts.sh

.PHONY: tern-sync tern-capture tern-status
tern-sync:
	./terminals/tern/install.sh sync $(if $(filter 1,$(FORCE)),--force,)

tern-capture:
	./terminals/tern/install.sh capture

tern-status:
	./terminals/tern/install.sh status

## 8.1 Config | render-configs | Render config templates
render-configs:
	./scripts/render-configs.sh

## 8.2 Config | private-sync | Sync private overlay
private-sync:
	./scripts/sync-private-overlay.sh

## 1.16 Common | privacy-audit | Redacted privacy scan
## 8.3 Config | privacy-audit | Scan for secrets
privacy-audit:
	./scripts/privacy-audit.sh

## 8.4 Config | privacy-audit-history | Scan with git history
privacy-audit-history:
	./scripts/privacy-audit.sh --history

## 8.5 Config | export-public DEST=… | Export public template
export-public:
	@test -n "$(DEST)" || (echo "Usage: make export-public DEST=/path/to/public-template" >&2; exit 2)
	./scripts/export-public-template.sh --dest "$(DEST)"

## 8.6 Config | publish-public | Publish public template
publish-public:
	@test -n "$(PUBLIC_REPO)$(PUBLIC_REMOTE)$(MAC_BOOTSTRAP_PUBLIC_REPO)$(MAC_BOOTSTRAP_PUBLIC_REMOTE)" || (echo "Usage: PUBLIC_REPO=owner/repo make publish-public" >&2; exit 2)
	./scripts/publish-public-template.sh

npm-packages:
	./scripts/install-npm-global-packages.sh --yes

npm-packages-upgrade:
	./scripts/install-npm-global-packages.sh --yes --upgrade

## 9.1 Other | pm-detect | Detect package manager
pm-detect:
	@./scripts/detect-package-manager.sh

## 9.2 Other | pm-set | Set global package manager
pm-set:
	@test -n "$(PM)" || { echo "Usage: make pm-set PM=<npm|pnpm|yarn|bun>" >&2; exit 2; }
	@./scripts/detect-package-manager.sh --set-global "$(PM)"

## 9.3 Other | mcp-profiles | Setup MCP profiles
mcp-profiles:
	./scripts/setup-mcp-profiles.sh

## 9.4 Other | hook-matchers | Add hook matchers
hook-matchers:
	./scripts/add-hook-matchers.sh

## 9.5 Other | patch-chrome-gemini | Patch Google Chrome Local State to enable Gemini
patch-chrome-gemini:
	TARGET_USER=$(if $(USER),$(USER),) KILL_CHROME=$(if $(KILL),$(KILL),$(KILL_CHROME)) ./scripts/patch-chrome-gemini.sh

install-maintenance-agents:
	./scripts/install-maintenance-agents.sh install

unload-maintenance-agents:
	./scripts/install-maintenance-agents.sh unload

system-patrol:
	./scripts/system-patrol.sh

# ── Claude Code Daemon ─────────────────────────────────────
## 6.1 Claude Daemon | claude-daemon-install | Install launchd keepalive daemon
claude-daemon-install:
	./scripts/install-maintenance-agents.sh install claude-daemon

## 6.3 Claude Daemon | claude-daemon-status | Show daemon status
claude-daemon-status:
	@echo "=== claude-daemon ==="
	launchctl print gui/$$(id -u)/io.local.mac-bootstrap.claude-daemon 2>&1 | head -20

## 6.4 Claude Daemon | claude-daemon-logs | Show daemon logs
claude-daemon-logs:
	@echo "=== Claude daemon logs ==="
	tail -20 "$(HOME)/Library/Logs/claude-daemon/daemon.log" 2>/dev/null || echo "(no daemon.log)"

## 6.2 Claude Daemon | claude-daemon-unload | Stop daemon services
claude-daemon-unload:
	./scripts/install-maintenance-agents.sh unload claude-daemon
	@echo "=== Claude daemon unloaded ==="
# ── System maxfiles limit (survives reboot) ─────────────────
# launchd's default global soft limit (256) is too low for tools like
# codex/context-mode that fan out many fds; this raises it at every boot.
## 7.1 System Limits | maxfiles-limit-install | Install LaunchDaemon raising launchd maxfiles (sudo)
maxfiles-limit-install:
	sudo cp "$(CURDIR)/launchd/io.local.mac-bootstrap.maxfiles.plist" /Library/LaunchDaemons/io.local.mac-bootstrap.maxfiles.plist
	sudo chown root:wheel /Library/LaunchDaemons/io.local.mac-bootstrap.maxfiles.plist
	sudo chmod 644 /Library/LaunchDaemons/io.local.mac-bootstrap.maxfiles.plist
	sudo launchctl bootout system/io.local.mac-bootstrap.maxfiles 2>/dev/null || true
	sudo launchctl bootstrap system /Library/LaunchDaemons/io.local.mac-bootstrap.maxfiles.plist
	@echo "=== maxfiles daemon installed. Effective now and on every future boot. ==="
	launchctl limit maxfiles

## 7.2 System Limits | maxfiles-limit-status | Show maxfiles daemon + current limit
maxfiles-limit-status:
	@echo "=== maxfiles daemon ==="
	sudo launchctl print system/io.local.mac-bootstrap.maxfiles 2>&1 | head -20
	@echo "--- current limit ---"
	launchctl limit maxfiles

## 7.3 System Limits | maxfiles-limit-uninstall | Remove maxfiles LaunchDaemon (sudo)
maxfiles-limit-uninstall:
	sudo launchctl bootout system/io.local.mac-bootstrap.maxfiles 2>/dev/null || true
	sudo rm -f /Library/LaunchDaemons/io.local.mac-bootstrap.maxfiles.plist
	@echo "=== maxfiles daemon uninstalled ==="

# ── Daemon & LaunchAgent Maintenance ──────────────────────────────
## 1.15 Common | cleanup-services | Audit & clean obsolete LaunchAgents and zombie daemon processes
cleanup-services:
	./scripts/cleanup-daemon-services.sh

# ── External Tools Manifest ──────────────────────────────────────────
## 1.25 Common | external-tools | Install/verify standalone CLI and external tools from manifest
external-tools:
	./scripts/install-external-tools.sh

## 5.1 Terminal & Theme | theme-switch | Switch terminal theme: THEME=catppuccin-mocha|gruvbox-dark
theme-switch:
	@test -n "$(THEME)" || (echo "Usage: make theme-switch THEME=catppuccin-mocha|gruvbox-dark" >&2; exit 2)
	./scripts/switch-terminal-theme.sh "$(THEME)"

## 5.2 Terminal & Theme | theme-list | List supported terminal themes
theme-list:
	@echo "catppuccin-mocha"
	@echo "gruvbox-dark"
## 10.2 ImgBed | imgup-install | Install imgup CLI symlink + validate config
imgup-install:
	./scripts/install-imgup.sh

## 10.1 ImgBed | imgup | Upload images to CloudFlare-ImgBed (alias for imgup-install)
imgup: imgup-install

# ── Cold Start (Proxy Bootstrap) ────────────────────────────────────
## 2.2 Bootstrap | cold-start | Install Clash Verge proxy (first step on fresh Mac)
cold-start:
	./scripts/install-clash.sh
cold-start-dry:
	./scripts/install-clash.sh --dry-run

# ── Network Tuning & Dynamic BDP (macOS Client) ──────────────────────
## 1.28 Common | net-tune | Adaptive network probe & macOS TCP window optimization
net-tune:
	./scripts/net-tune-macos.sh tune $(if $(PROFILE),$(PROFILE),) $(if $(APPLY),--apply,)

## 1.29 Common | net-tune-apply | Apply dynamic macOS TCP window tuning (requires sudo)
net-tune-apply:
	./scripts/net-tune-macos.sh tune $(if $(PROFILE),$(PROFILE),) --apply

net-tune-save:
	./scripts/net-tune-macos.sh save $(if $(PROFILE),$(PROFILE),home)

net-tune-auto:
	./scripts/net-tune-macos.sh auto

net-tune-list:
	./scripts/net-tune-macos.sh list

## 1.30 Common | net-tune-status | Show current macOS TCP socket parameters
net-tune-status:
	./scripts/net-tune-macos.sh status

## 1.31 Common | net-tune-restore | Restore macOS stock TCP socket defaults
net-tune-restore:
	./scripts/net-tune-macos.sh restore
