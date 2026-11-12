# mac-bootstrap 模板规则

- 模板必须保持公开、可复用、可迁移。
- 先读 `CONTEXT.md`；专题操作见 `docs/`。
- 真实机器差异由父仓 overlay 提供，不在模板复制。
- 不直接修改运行态、缓存或生成文件。
- 修改后先运行最小相关验证；跨模块变更运行 `make check`。
- 删除功能、配置项或运行态组件时，同一变更集必须
  `grep -rn '<符号>' tests/ docs/` 并同步清理残留断言与引用；
  machine 合同测试仅在父仓 pre-push 本机执行，CI 不会发现漏删。
- 公共发布前运行 `make privacy-audit`。
- `README.md` 是人类入口；本文件仅保留执行约束。

## Default development workflow

For non-trivial implementation, bug-fix, or security-sensitive work:
- Start from a spec or ticket; shape missing acceptance criteria with `/to-spec` and pin the review base.
- Run `/implement` through implementation and focused checks; stop before its commit step. If it cannot pause, follow its steps manually. Apply `/tdd` when a test seam exists.
- Finish with `/code-review` on the complete pinned change; it launches parallel spec and standards review subagents.
- For security-sensitive changes, launch the host's supported `security-reviewer` subagent independently on that same change, including tracked and untracked files; unavailable is a blocker.
- Require a `## Security` report with scope, evidence, severity (`blocker|critical|high|major|medium|minor|low`), and disposition (`fixed|accepted`); `none` is valid. Missing or unknown fields block.
- Complete with smoke-test evidence; block commit on blocker/critical/high/major findings, require owner and rationale for accepted lower findings, and reconfirm the reviewed change is unchanged.

## Agent skills
### Maintenance guide

Skills follow the supply chain documented in `agent-skills/README.md` (authoritative)
with lineage/gate in `agent-skills/registry/*.jsonc`. One authoritative source per
Skill; every runtime view (`~/.claude/skills`, `~/.agents/skills`,
`~/.codex/skills`, project `.agents/skills`, `~/.omp/agent/managed-skills`) is a
directory symlink to that same source. Never hand-edit runtime skill directories,
and never leave `.bak`/`.old`/`.tmp`/manual copies holding `SKILL.md` (runtimes
register every such subdirectory → duplicate/conflicting defs). To add or adjust a
Skill, edit the source under `agent-skills/local/<project>/<name>/SKILL.md` (or
`local/global/` for global), then roll out through the registry CLI:

```bash
make skill-plan
make skill-check
python3 scripts/skill_supply_chain.py distribute --dry-run
make skill-snapshot LABEL=pre-change
make skill-reconcile
```

Managed Skills format: one-level `<name>/SKILL.md`, lowercase-hyphenated `name`
(1–64 chars), non-empty `description` (≤1024 chars); `scripts/`, `references/`,
`assets/` stay inside the same source directory.
- `prd-score-optimization` 源目录 `agent-skills/local/global/prd-score-optimization/`；迭代重算流程与缓存/fiber/module_id 等踩坑记录于其 `references/lessons.md`。
### Issue tracker

GitHub Issues in `suainam/mac-bootstrap-template` are the source for specs and
tickets. See `docs/agents/issue-tracker.md`.

### Domain docs

This is a single-context repository; read `CONTEXT.md` and relevant `docs/`
guidance before implementation. See `docs/agents/domain.md`.

For Hammerspoon configuration or runtime work, read
`desktop/hammerspoon/README.md` before editing or reloading the app.
