# Data Hub 参考手册

> 目录契约、产物契约、runtime config、summary quarantine 约定。

## 目录约定

### Shared Knowledge Root

```text
~/work/knowledge/
├── .llm-wiki/
├── .obsidian/
├── raw/
│   └── sources/
├── wiki/
├── purpose.md
├── schema.md
├── 00_System/
├── 10_Periodic/
│   └── Daily/
├── 20_Projects/
├── 30_Areas/
├── 40_Knowledge/
├── 60_Inbox/
├── 70_Summaries/
│   ├── Daily/
│   ├── Weekly/
│   ├── Monthly/
│   ├── Quarterly/
│   └── Yearly/
└── 90_Archive/
```

补充：

- `10_Periodic/Weekly|Monthly|Quarterly|Yearly/` 旧 dataview 目录未来不再保留
- `10_Periodic/Daily/` 保留给 `llm_wiki`
- `70_Summaries/` 是自动总结半成品层，`70_Summaries/Daily` 是 weekly 的上一层输入

### Ownership

- `llm_wiki` owns: `.llm-wiki/`, `raw/`, `wiki/`, `purpose.md`, `schema.md`
- `llm_wiki` indexes: `10_Periodic/Daily/`
- `data-hub` owns: `60_Inbox/`, `70_Summaries/`, SQLite, summary lineage, `40_Knowledge/` 工作知识投影

### Daily Contract

`10_Periodic/Daily/` 是：

- 随手记输入面
- 时间线输入
- `llm_wiki` 的第一输入面

不是：

- `data-hub` 的 canonical state
- 正式周报/月报/季报存放位置

### Summary Quarantine Contract

`70_Summaries/` 是：

- 日报 / 周报 / 月报 / 季报 / 年报自动生成目录
- 半成品层
- 默认不被 `llm_wiki` 索引

上一层链路固定为：`Daily -> Weekly -> Monthly -> Quarterly -> Yearly`。生成 weekly/monthly/quarterly/yearly 前必须检查上一层完整性，并按 `summary.deployment_start` 截断，避免补部署前不存在的日期。

`70_Summaries/` 不是：

- 最终知识库
- 自动回流源
- `llm_wiki` 的 source bucket

### Promotion Contract

默认晋升路径：

```text
70_Summaries/*
  -> human review
  -> 40_Knowledge/*
  -> optional curation into llm_wiki
```

原则：

- 默认先晋升到 `40_Knowledge/`
- 只有必要时再整理进 `llm_wiki`
- summary 不是整篇迁移，而是挑出稳定结论、方法、决策、卡片级知识

## 外部材料放法

推荐入口：`~/work/knowledge/raw/sources/<family>/`

命名带日期前缀：

```text
2026-07-04_weekly-sync_product.md
2026-07-04_data-hub-architecture.md
2026-07-04_growth-analysis.xmind
2026-07-04_vendor-brief.pdf
2026-07-04_confluence-export.html
```

若文件名以 `YYYY-MM-DD_` 开头，按该日期归入对应日报；否则按首次落库日期归入。

## `llm_wiki` 接入边界

- `llm_wiki` 是 source/wiki layer
- `daily` 和外部资料优先由 `llm_wiki` 理解
- `data-hub` 通过 API context 使用 `llm_wiki`
- `data-hub` 不直接写 `wiki/`

```text
Daily + raw/sources
  -> llm_wiki ingest
  -> search / graph / review / API
  -> data-hub retrieval / summary / promotion
```

## Runtime Config

主配置文件：`private/agent/data_hub.runtime.jsonc`  
公开样例：`template/agent/data-hub/data_hub.runtime.jsonc.example`

它集中管理：

- `paths`
- `sources.inputs`
- `llm_wiki`
- `summary`
- `agent_logs`
- `llm.backends`
- `workflow`

优先级：显式 shell 环境变量 > runtime config > 代码默认值。

### Source Bucket 说明

当前 template 默认 source bucket 是 `raw/sources/*`：

```text
raw/sources/Meetings
raw/sources/Mindmaps
raw/sources/Wiki-Clips
```

`50_Sources/*` 是旧验收样本和历史文档里的路径，不是 shared-root v2 目标结构。

shared-root 环境下，真实路径仍以 private runtime config 为准；如需迁移目录，只改 `sources.inputs`，不要在代码里重新引入 `50_Sources` 默认值。

### `llm_wiki` API 说明

data-hub 当前使用的 API 契约：

| 用途 | Endpoint |
|---|---|
| 健康检查 | `GET /api/v1/health` |
| 项目列表 | `GET /api/v1/projects` |
| 语义检索 | `POST /api/v1/projects/{id}/search` |
| 文件内容 | `GET /api/v1/projects/{id}/files/content` |
| 图谱 | `GET /api/v1/projects/{id}/graph` |
| review 队列 | `GET /api/v1/projects/{id}/reviews?status=unresolved` |

protected API 需要 token。优先使用 `LLM_WIKI_TOKEN`，其次读取 private runtime 的 `llm_wiki.token`。

## 产物契约

### `70_Summaries/*` frontmatter 最低约定

```yaml
type: summary
summary_level: daily | weekly | monthly | quarterly | yearly
status: draft | reviewed | promoted_partially | archived
generated_by: data-hub
indexing: excluded
source_mode: daily-first
derived_from:
  - daily
  - sqlite_records
  - llm_wiki_context
promotion_status: not_reviewed
```

### `40_Knowledge/*` 从 summary 晋升时的建议字段

```yaml
promoted_from: 70_Summaries/Weekly/2026-W28.md
promotion_reason:
source_refs:
```

## Canonical State vs Projection

| 层 | 实体 | 角色 |
|---|---|---|
| input memory | `10_Periodic/Daily/` | 人类工作痕迹，`llm_wiki` 输入 |
| canonical state | SQLite | 主动沉淀、review、lineage、summary run metadata |
| quarantine projection | `70_Summaries/` | 自动总结半成品 |
| long-term knowledge | `40_Knowledge/` | 人工确认后的长期工作知识 |

## Anti-Loop Checklist

- `70_Summaries/` 是否已加入 `llm_wiki exclude`
- summary workflow 是否避免读取同层 summary
- `daily` 与 SQLite 重复事实是否做去重
- 是否阻止了 summary 自动直写 `40_Knowledge/`
- 是否阻止了 summary 自动回流 `llm_wiki`
