---
name: mac-bootstrap-maintenance
description: Maintain the mac-bootstrap dotfiles system with private parent repo and public template submodule. Use when updating templates, syncing submodule pointers, running privacy audits, cleaning branches, or troubleshooting the bootstrap system.
---

# mac-bootstrap Maintenance

Private parent (`mac-bootstrap`) + public child (`mac-bootstrap-template` submodule).
Parent is a thin wrapper; all real config lives in the template.

## Quick start

```bash
# Full status check
make check && make submodule-status && git status

# After editing template files
bash .agents/skills/mac-bootstrap-maintenance/scripts/sync-template.sh

# Privacy audit before push
make privacy-audit

# Clean up merged branches
bash .agents/skills/mac-bootstrap-maintenance/scripts/clean-branches.sh
```

## Workflows

### Update template

1. Edit files under `template/`
2. Run `scripts/sync-template.sh` — pulls latest, verifies, commits, pushes
3. Or manually: commit in template, then `git add template && git commit && git push`

### Privacy audit

```bash
make privacy-audit
# or detailed scan:
bash .agents/skills/mac-bootstrap-maintenance/scripts/privacy-check.sh
```

### Clean merged branches

```bash
bash .agents/skills/mac-bootstrap-maintenance/scripts/clean-branches.sh
```

### Initialize after clone

```bash
git submodule update --init --recursive
# or: make submodule-init
```

## Critical rules

1. **NEVER push private content to the public template repo.**
2. **Always run `make check` before pushing parent.**
3. **After editing template, sync the submodule pointer in parent.**
4. **Edit `template/install.sh`, not the parent wrapper `install.sh`.**

## Architecture details

See [REFERENCE.md](REFERENCE.md) for full file inventory, privacy layers, and pitfalls.
