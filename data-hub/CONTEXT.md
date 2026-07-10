# Data Hub Context

`data-hub` 采用“双系统”模型：

- `llm_wiki`：理解 `daily` 与外部资料，提供 search / graph / review / API context
- `data-hub`：管理主动沉淀、SQLite 状态账本、周期总结编排、知识晋升

执行约束看 [AGENTS.md](./AGENTS.md)。详细契约看 [docs/reference.md](./docs/reference.md)。

## 1. Shared Knowledge Root

```text
<knowledge-root>
├── .llm-wiki
├── raw/sources
├── wiki
├── purpose.md
├── schema.md
├── 10_Periodic/Daily
├── 40_Knowledge
├── 60_Inbox
├── 70_Summaries/{Daily,Weekly,Monthly,Quarterly,Yearly}
└── ...
```

稳定结论：

- `10_Periodic/Daily/` 是随手记输入面
- `70_Summaries/` 是自动总结半成品层
- `10_Periodic/Weekly|Monthly|Quarterly|Yearly` 属于旧 dataview 产物，未来不再保留

## 2. Ownership

`llm_wiki` owns:

- `.llm-wiki/`
- `raw/`
- `wiki/`
- `purpose.md`
- `schema.md`
- `10_Periodic/Daily/` 的索引与理解权

`data-hub` owns:

- SQLite state ledger
- `60_Inbox/`
- `70_Summaries/`
- summary workflow / scheduler / lineage
- `40_Knowledge/` 中由主动沉淀或人工晋升形成的工作知识投影

## 3. Canonical State

不同层的“真相”不同：

- `daily`：真实工作痕迹输入，但不是 `data-hub` 的 canonical state
- SQLite：`data-hub` 的 canonical state
- `70_Summaries`：自动生成半成品，不是 canonical state
- `40_Knowledge`：人工确认后的长期工作知识

因此：

- `data-hub` 不保存 `daily` 原文
- `data-hub` 不直接写 `wiki/`
- 周期总结不自动回流知识库

## 4. 四条数据流

### Daily Flow

```text
daily
  -> 10_Periodic/Daily/*.md
  -> llm_wiki ingest/index
  -> wiki/search/graph/review/API
```

### External Source Flow

```text
external docs
  -> raw/sources/*
  -> llm_wiki ingest/index
  -> wiki/search/graph/review/API
```

### Active Record Flow

```text
agent chat / manual record / git commit / push
  -> knowledge-record / knowledge-lifecycle-manager
  -> SQLite
```

### Period Summary Flow

```text
Daily / SQLite records / landed sources
+ llm_wiki search + Deep Chat citations
  -> deterministic evidence groups
  -> JSON-contract synthesis
  -> immutable SQLite revision
  -> deterministic `70_Summaries/{Daily,Weekly,Monthly,Quarterly,Yearly}` projection
```

## 5. Anti-Loop Rules

1. `70_Summaries/` 必须被 `llm_wiki exclude`
2. 周期总结不能读取自己或同层 summary 作为主要输入；weekly 读取 daily，monthly 读取 weekly，quarterly 读取 monthly，yearly 读取 quarterly
3. 同一事实若同时存在于 `daily` 和 SQLite，summary 层必须去重
4. Summary JSON、item dimensions 与 evidence group IDs 必须先落 SQLite；Markdown renderer 不推断或补写事实
5. `70_Summaries -> 40_Knowledge -> optional llm_wiki` 必须经过人工 gate

## 6. 当前实现状态

当前 template 已落地双系统主干：

- source bucket 默认指向 `raw/sources/*`
- `summary_evidence.py` 只读合并本地证据与 `llm_wiki` Deep Chat citations；`70_Summaries/` 永不作为 primary evidence
- `build_<level>_summary` 生成 immutable revision，再原子投影到 `70_Summaries/`；lower layer 只从 SQLite published revisions 读取
- 09:00/17:30 按 `chinese_calendar` 工作日执行，18:00 每日从低到高调度 eligible levels
- `promote_summary_knowledge.py` 提供人工挑选晋升到 `40_Knowledge/` 的 gate
- `data_hub.runtime.jsonc.example` 暴露 `llm_wiki` 与 summary runtime 配置

仍需人工保证的外部事实：

- `70_Summaries/` 已在真实 llm_wiki 项目 exclude 中配置
- protected API 需要在 llm_wiki 设置里生成 token，并通过 `LLM_WIKI_TOKEN` 或 private runtime 提供
- 旧 `10_Periodic/Weekly|Monthly|Quarterly|Yearly` dataview 文件不再作为 data-hub 产物依赖

这份文档的职责是固定边界，避免后续实现继续跑偏。完整设计见 [../../docs/superpowers/specs/2026-07-09-data-hub-dual-system-design.md](../../docs/superpowers/specs/2026-07-09-data-hub-dual-system-design.md)。
