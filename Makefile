SHELL := /usr/bin/env bash

.PHONY: bootstrap check doctor clean-cache clean-cache-aggressive cache-report \
	install-cache-agent organize-downloads install-downloads-agent \
	install-antigravity-cli install agent-sync agent-tools security-scan instinct-sync \
	render-configs private-sync privacy-audit privacy-audit-history export-public publish-public

bootstrap install:
	./install.sh --yes --with-vim --with-tmux --cleanup
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
	bash -n tmux/install.sh
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
