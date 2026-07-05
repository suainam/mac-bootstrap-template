# Data Hub 参考手册

> 目录约定、环境变量、Obsidian 插件、幂等性约定。

## 目录约定

### Obsidian Vault 结构

```text
~/work/knowledge/
├── 00_System/    Templates/ · Dashboards/ · Reports/
├── 10_Periodic/  Daily/ · Weekly/ · Monthly/ · Quarterly/ · Yearly/
├── 20_Projects/
├── 30_Areas/
├── 40_Knowledge/ ADR/ · Cards/ · Methods/ · Metrics/ · Playbooks/ · Wiki/
├── 50_Sources/   Meetings/ · Wiki-Clips/ · Mindmaps/ · Imports/
├── 60_Inbox/     Candidates/ · Review-Queue/
└── 90_Archive/
```

### 外部材料放法

放入 `~/work/knowledge/50_Sources/<family>/`，命名带日期前缀：

```
2026-07-04_weekly-sync_product.md
2026-07-04_data-hub-architecture.md
2026-07-04_growth-analysis.xmind
2026-07-04_vendor-brief.pdf
2026-07-04_confluence-export.html
```

若文件名以 `YYYY-MM-DD_` 开头，按该日期归入对应日报；否则按首次落库日期归入。

### 机器处理层

```text
~/work/data/agent-hub/
├── db/            SQLite 账本
├── ingest/
├── parsed/
├── extracted/
├── review-packets/
└── logs/
```

`knowledge/` 给人和 Obsidian 用；`data/agent-hub/` 给脚本和中间产物。

## 环境变量

配置文件：`private/agent/.obsidian_daily.env`

```bash
OBSIDIAN_VAULT_DIR="$HOME/work/knowledge"
OBSIDIAN_DAILY_DIR="10_Periodic/Daily"
GIT_SEARCH_ROOTS="$HOME/work/config,$HOME/work/projects"
AGENT_DB_PATH="$HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db"
# AGENT_RUNS_DIR="$HOME/work/config/mac-bootstrap/private/agent/data/runs"
# EXTERNAL_SOURCE_DATE_MODE="filename_first"  # 默认值，一般不需要改
```

| 变量 | 说明 |
|------|------|
| `OBSIDIAN_VAULT_DIR` | Vault 根目录 |
| `OBSIDIAN_DAILY_DIR` | 日报子目录（相对 Vault） |
| `GIT_SEARCH_ROOTS` | Git 活动搜索根，逗号分隔 |
| `AGENT_DB_PATH` | SQLite 账本绝对路径 |
| `AGENT_RUNS_DIR` | durable workflow stdout/stderr 日志目录，默认在 DB 同级 `runs/` |
| `EXTERNAL_SOURCE_DATE_MODE` | 外部材料日期归因策略，默认 `filename_first` |

## Obsidian 插件约定

插件目录必须与 Vault 结构保持一致：

| 插件 | 目录 |
|------|------|
| daily-notes | `10_Periodic/Daily` |
| periodic-notes | `10_Periodic/{Daily,Weekly,Monthly,Quarterly,Yearly}` |
| templates | `00_System/Templates` |
| templater | `00_System/Templates` |

如果 Obsidian 表现异常，优先检查：
- `.obsidian/daily-notes.json`
- `.obsidian/templates.json`
- `.obsidian/plugins/periodic-notes/data.json`
- `.obsidian/plugins/templater-obsidian/data.json`

### Dataview 路径约定（2026-07-05 修复）

周报/月报/季报/年报模板用 `dv.pages('"文件夹路径"')` 聚合日报时，**必须使用完整大写路径，不能用小写缩写**：

| 模板 | 正确查询 | 错误写法（大小写不匹配，返回空） |
|------|---------|-------------------------------|
| `weekly.md` | `dv.pages('"10_Periodic/Daily"')` | `dv.pages('"daily"')` |
| `monthly.md` | `dv.pages('"10_Periodic/Daily"')` + `dv.pages('"10_Periodic/Weekly"')` | `dv.pages('"daily"')` |
| `quarterly.md` | `dv.pages('"10_Periodic/Monthly"')` | `dv.pages('"monthly"')` |
| `yearly.md` | `dv.pages('"10_Periodic/Quarterly"')` | `dv.pages('"quarterly"')` |

Dataview 按文件夹路径过滤时**区分大小写**；vault 实际目录是 `Daily/`（大写），小写路径永远返回空集合。

## Canonical State vs Projection

数据层有两种角色，不能混淆：

| 角色 | 实体 | 特性 |
|------|------|------|
| **Canonical State** | SQLite（`agent_history.db`） | 唯一真相，只增不删（除孤儿清理），所有状态以此为准 |
| **Projection** | Obsidian vault 笔记 | 可由 SQLite 重建，允许被 LLM/人工覆盖，不是 source of truth |

推论：
- Obsidian 日报、ADR、Cards — 丢了可重建，跑 `materialize_candidates.py` 还原
- SQLite 里的 `review_action`（accept/reject）— 不可从 vault 反推，必须备份 DB
- `generate_candidates.py` 生成的 review markdown — 是 Projection，幂等重写无损

备份策略：只需备份 `AGENT_DB_PATH`，vault 内容可重建。

## Durable Workflow State

工业化运行新增 4 类状态表：

| 表 | 用途 |
|----|------|
| `workflow_runs` | workflow 级 run_id、状态、日期、错误 |
| `workflow_steps` | step 级 attempt、exit_code、日志路径、输入/输出 hash |
| `artifact_manifest` | stdout/stderr 等产物登记 |
| `backup_log` | SQLite 备份路径、checksum、结果 |

`execution_log` 保留给单个脚本内部记录；`workflow_*` 负责跨脚本编排和恢复。

## 幂等性约定

| 脚本 | 幂等策略 |
|------|---------|
| `ingest_logs.py` | SQLite 按现有去重/增量逻辑，不重复写入 |
| `ingest_sources.py` | source 未变化直接跳过；变化时重建该 document 的 chunks/items |
| `generate_candidates.py` | 对 `extracted_item_id` 做 upsert；不重置已审核状态；markdown 审核清单每次整文件重写 |
| `daily_summary.py` | 只重写 `## AI 总结` 一节，不重复追加 |
| `materialize_candidates.py` | `daily` 依赖 `<!-- knowledge_candidate:<id> -->` marker 防重复；`adr/card` 依赖 frontmatter `candidate_id` 防重复 |

层级职责：
- `SQLite` = 状态账本（唯一真相）
- `候选 review markdown` = 可重建视图
- `Obsidian materialized note` = 带 trace id 的投影层
