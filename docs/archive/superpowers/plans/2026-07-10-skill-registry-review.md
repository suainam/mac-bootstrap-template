# Skill Registry Review

> Historical record only; registry counts in this review are not current. Use `agent-skills/registry/` and `docs/skill-supply-chain.md`.

> `90` 是 registry 纳管条目数，不等于当前都安装。只有 `enabled` 参与新分发；`staged` 是保留来源待审，`disabled` 是不分发，`merged` 是被其他 skill 覆盖或合并。

## Summary

| Metric | Count |
|---|---:|
| Total registry entries | 90 |
| state=enabled | 56 |
| state=staged | 19 |
| state=disabled | 9 |
| state=merged | 6 |
| source_type=external | 57 |
| source_type=internal | 33 |
| scope=global | 57 |
| scope=project | 33 |

## Source lineage corrections already applied

| Source | Skill | State | Scope | Ref | Local shadow | Note |
|---|---|---|---|---|---|---|
| `mattpocock-skills` | `caveman` | enabled | global | `https://github.com/mattpocock/skills` | `agent/skills/personal/caveman` | skills.sh page shows `npx skills add https://github.com/mattpocock/skills --skill caveman` |
| `langgpt` | `langgpt-prompt-writer` | staged | global | `https://github.com/langgptai/LangGPT/blob/main/README_zh.md#方法五claude-code-skill推荐` | `agent/skills/personal/langgpt-prompt-writer` | LangGPT README recommends Claude Code Skill via marketplace/manual install; staged until install path is automated |
| `qiaomu-goal-meta-skill` | `qiaomu-goal-meta-skill` | enabled | global | `joeseesun/qiaomu-goal-meta-skill` | `agent/skills/personal/qiaomu-goal-meta-skill` | upstream README installs with `npx skills add joeseesun/qiaomu-goal-meta-skill` |
| `local-personal` | `caveman-commit` | disabled | global |  |  | retired after caveman source moved to mattpocock/skills |
| `local-personal` | `caveman-help` | disabled | global |  |  | retired after caveman source moved to mattpocock/skills |
| `local-personal` | `caveman-review` | disabled | global |  |  | retired after caveman source moved to mattpocock/skills |

## Enabled but not fully installed in current production runtime

| Scope | Source | Skill | Target | Installed | Present in |
|---|---|---|---|---:|---|
| global | `mattpocock-skills` | `diagnose` | claude, codex, opencode, cross-agent | 0/4 | - |
| global | `vercel-skills` | `find-skills` | claude, codex, opencode, cross-agent | 0/4 | - |
| project | `baoyu-skills` | `baoyu-diagram` | product_strategy | 0/1 | - |
| project | `baoyu-skills` | `baoyu-infographic` | product_strategy | 0/1 | - |
| project | `garden-skills` | `beautiful-article` | product_strategy | 0/1 | - |
| project | `garden-skills` | `gpt-image-2` | product_strategy | 0/1 | - |
| project | `garden-skills` | `kb-retriever` | mac-bootstrap | 0/1 | - |
| project | `garden-skills` | `web-design-engineer` | product_strategy | 0/1 | - |
| project | `garden-skills` | `web-video-presentation` | product_strategy | 0/1 | - |
| project | `khazix-skills` | `aihot` | mac-bootstrap | 0/1 | - |
| project | `local-personal` | `franchise-store-sankey-analysis` | franchise_store | 0/1 | - |
| project | `local-personal` | `knowledge-record` | mac-bootstrap | 0/1 | - |
| project | `local-personal` | `python-data-analysis` | product_strategy | 0/1 | - |
| project | `local-personal` | `sankey-flow-analysis` | franchise_store | 0/1 | - |
| project | `local-personal` | `web-video-presentation-delivery` | product_strategy | 0/1 | - |
| project | `local-standalone` | `daily-tagger` | mac-bootstrap | 0/1 | - |

## Review focus

### Keep enabled unless you want to reduce active surface

These are enabled and will be installed by the new distributor once the source exists and gates pass. The biggest active-surface additions relative to current production runtime are `find-skills`, `diagnose`, the product_strategy visual/content skills, and project skills currently missing from their `.agents/skills` views.

### Staged but currently present in runtime

These are not planned for new distribution, but still exist in current runtime. They should be cleaned only after the post-distribution snapshot proves no workflow depends on them:

- `codebase-memory`
- `data-scraper-agent`
- `database-migrations`
- `postgres-patterns`
- `langgpt-prompt-writer`
- `cavecrew`
- `caveman-compress`
- `caveman-stats`
- `grill-with-docs`
- `handoff`
- `writing-great-skills`
- `json-canvas`
- `obsidian-bases`

### Disabled but currently present in runtime

These are explicit cleanup candidates:

- `clickhouse-io`
- `mle-workflow`
- `pytorch-patterns`
- `caveman-commit`
- `caveman-help`
- `caveman-review`
- `docker-data-project`
- `setup-matt-pocock-skills`
- `playwright`

### Merged but currently present in runtime

These should eventually disappear from runtime after their replacement path is confirmed:

- `python-patterns`
- `tdd-workflow`
- `verification-loop`
- `eval-loop`
- `tdd`
- `test-driven-development`
