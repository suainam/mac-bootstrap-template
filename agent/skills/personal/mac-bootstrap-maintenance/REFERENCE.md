# mac-bootstrap Architecture Reference

## Repository Layout

```
mac-bootstrap/                  (private parent)
├── .gitignore                 屏蔽 private/、.env、*.pem 等
├── .gitmodules                 指向 mac-bootstrap-template
├── Makefile                    父仓检查 + 委托子仓
├── install.sh                  薄 wrapper → exec template/install.sh
├── bootstrap.sh                薄 wrapper → exec template/install.sh
├── README.md
├── template/                   submodule → suainam/mac-bootstrap-template (public)
└── private/                    本地目录，不在 git tree 中
```

## File Inventory

### Parent repo (private) — only these files are tracked

| File | Purpose |
|------|---------|
| `.gitignore` | 屏蔽 private/、.env、*.pem、*.key 等敏感文件 |
| `.gitmodules` | 指向 public template submodule |
| `Makefile` | make check / privacy-audit / update-template |
| `README.md` | 使用说明 |
| `bootstrap.sh` | 入口 wrapper，exec template/install.sh |
| `install.sh` | 入口 wrapper，exec template/install.sh |

### Template repo (public) — all config files live here

Directories: `agent/`, `desktop/`, `docs/`, `editors/`, `infra/`, `launchd/`,
`multiplexer/`, `private.example/`, `proxy/`, `scripts/`, `shell/`,
`terminals/`, `tests/`, `workspace/`

Key files: `Brewfile`, `CONTEXT.md`, `Makefile`, `README.md`, `install.sh`

## Privacy Layers

1. **`.gitignore`** — prevents private files from entering parent git tree
2. **`.publicignore`** — prevents private files from being exported to public template
3. **`parent-privacy-audit`** — grep for AWS/SSH/Slack/OpenAI/GitHub secrets in parent (excludes template/)
4. **`privacy-audit`** — runs `scripts/privacy-audit.sh` in template, suppresses values
5. **This skill's `privacy-check.sh`** — scans both repos + checks template tree for private files

## Common Pitfalls

### 1. Forgetting to sync submodule pointer

After editing template, parent still points to old commit. Always run:
```bash
rtk git add template && rtk git commit -m "Update template submodule"
```

### 2. Pushing private content to public template

Before any push to template repo, run `make privacy-audit`. Never commit:
- `private/` directory
- `.env` files with real values
- SSH keys, API tokens, passwords
- Machine-specific paths containing usernames

### 3. Parent repo accumulates stale branches

Use `scripts/clean-branches.sh` after merging to delete local + remote branches.

### 4. Template submodule not initialized

After cloning parent, always run:
```bash
git submodule update --init --recursive
```
Or: `make submodule-init`

### 5. Editing wrapper scripts instead of template

`install.sh` and `bootstrap.sh` in parent are thin wrappers. All real logic is in
`template/install.sh`. Edit the template, not the wrapper.

### 6. Submodule git operations fail with `index.lock`

`git -C template add/commit` may need permissions outside the sandbox because
git writes metadata under `.git/modules/template/`. If you see
`Unable to create ... .git/modules/template/index.lock`, retry the exact git
operation with the required permissions; do not rewrite history or bypass the
child-first publish order.

### 7. `make check` accidentally uses a temporary uv environment

Template regression should run from `template/.venv`, not `uv run --with ...`.
Using `--with` can pull ad-hoc dependencies from the network and test a
different environment than the one the repo actually maintains.

### 8. Parallel checks can create false daemon test failures

Do not run `make -C template check` and parent `make check` at the same time.
Both paths execute the `claude-daemon` tests, and parallel runs can trip the
shared lock and fail with `SKIP: another instance running`.

### 9. Sandbox tmux failures are not tmux config regressions

If tmux tests fail with `error connecting to /private/tmp/tmux-...`, the
sandbox likely cannot access the live tmux socket. Rerun the test outside the
sandbox before changing tmux bindings or themes.
