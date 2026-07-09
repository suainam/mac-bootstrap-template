# Data Hub Context

`data-hub` 采用“双系统”模型：

- `llm_wiki`：理解 `daily` 与外部资料，提供 search / graph / review / API context
- `data-hub`：管理主动沉淀、SQLite 状态账本、周期总结编排、知识晋升

执行约束看 [AGENTS.md](./AGENTS.md)。详细契约看 [docs/reference.md](./docs/reference.md)。

## 1. Shared Knowledge Root

```text
/Users/suai/work/knowledge
├── .llm-wiki
├── raw/sources
├── wiki
├── purpose.md
├── schema.md
├── 10_Periodic/Daily
├── 40_Knowledge
├── 60_Inbox
├── 70_Summaries/{Weekly,Monthly,Quarterly,Yearly}
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
daily-first retrieval
+ SQLite records
+ llm_wiki API context
  -> llm_filter
  -> 70_Summaries/{Weekly,Monthly,Quarterly,Yearly}
```

## 5. Anti-Loop Rules

1. `70_Summaries/` 必须被 `llm_wiki exclude`
2. 周期总结不能读取自己或同层 summary 作为主要输入
3. 同一事实若同时存在于 `daily` 和 SQLite，summary 层必须去重
4. `llm_filter` 是处理层，不是 canonical state
5. `70_Summaries -> 40_Knowledge -> optional llm_wiki` 必须经过人工 gate

## 6. 当前实现差异

目标模型已经定稿，但当前代码仍有 legacy 痕迹：

- source bucket 默认值仍可能指向 `50_Sources/*`
- `knowledge_retrieval.py` 还没完整接入 `llm_wiki` context merge
- `70_Summaries/` 的自动化还未完成

这份文档的职责是固定边界，避免后续实现继续跑偏。完整设计见 [../../docs/superpowers/specs/2026-07-09-data-hub-dual-system-design.md](../../docs/superpowers/specs/2026-07-09-data-hub-dual-system-design.md)。
