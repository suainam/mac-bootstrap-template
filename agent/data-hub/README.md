# Agent Data Hub

把个人知识自动化拆成两个并列系统：

- `llm_wiki`：理解 `daily` 与外部资料，提供 search / graph / review / API context
- `data-hub`：管理主动沉淀、SQLite 状态账本、周期总结编排、知识晋升

这里的 `data-hub` 直接负责两件事：

- 管状态：SQLite、review status、materialization ledger、workflow run state
- 管总结与投影：把已确认知识渲染到工作知识目录，并把周期总结写入隔离层

它不拥有外部资料智能层，也不拥有 `daily` 原文。那一层现在由同一个 knowledge root 里的 `llm_wiki` 负责。

## 先看什么

- [CONTEXT.md](./CONTEXT.md) — 系统模型、目录 ownership、canonical state、数据流
- [AGENTS.md](./AGENTS.md) — agent 修改边界、验证要求、文档路由
- [docs/ops.md](./docs/ops.md) — 日常运行、补跑、恢复、验收
- [docs/reference.md](./docs/reference.md) — 目录约定、runtime config、source bucket 配置
- [docs/troubleshooting.md](./docs/troubleshooting.md) — 常见故障排查
- [docs/README.md](./docs/README.md) — `docs/` 目录边界与索引
- [docs/acceptance-report.md](./docs/acceptance-report.md) — 已有真实验收记录
- [docs/upgrade-plan.md](./docs/upgrade-plan.md) — 历史升级设计稿
- [../../docs/superpowers/specs/2026-07-09-data-hub-dual-system-design.md](../../docs/superpowers/specs/2026-07-09-data-hub-dual-system-design.md) — 双系统正式设计稿

## 人类视角的主流程

```text
daily + raw/sources
  -> llm_wiki
  -> search / graph / review / API context

agent chat / manual record / git events
  -> data-hub SQLite

daily-first retrieval
+ SQLite records
+ llm_wiki context
  -> llm_filter
  -> 70_Summaries
  -> optional human promotion
```

并行关系：

```text
llm_wiki      -> retrievable knowledge layer
data-hub      -> state / workflow / promotion layer
70_Summaries  -> quarantine summary layer
Obsidian      -> viewer / editor for Markdown artifacts
```

## Knowledge Root 边界

`/Users/suai/work/knowledge` 是共享 knowledge root。

`llm_wiki` 拥有：

- `.llm-wiki/`
- `raw/`
- `wiki/`
- `purpose.md`
- `schema.md`

`data-hub` 拥有：

- `00_System/`
- `60_Inbox/`
- `70_Summaries/`
- `20_Projects/`
- `30_Areas/`
- `40_Knowledge/`
- `90_Archive/`

原则：

- `llm_wiki` 可以搜索和展示 data-hub 产物，但不能 ingest、重写、维护 data-hub-owned 目录
- `data-hub` 可以读取 `llm_wiki` 提供的上下文，但不能直接写 `wiki/`
- `10_Periodic/Daily/` 给 `llm_wiki`，不是 `data-hub` 的 canonical state
- `70_Summaries/` 默认不被 `llm_wiki` 索引，不自动回流知识库
- `50_Sources` 不再是推荐的真实目录名；在新布局里它只是语义名，实际 source 域应落在 `raw/sources`

## 当前实现入口

统一入口：

```bash
cd ~/work/config/mac-bootstrap
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow full_cycle --date 2026-07-09
```

当前 template 内已落地的 workflow 名称：

- `archive_to_sqlite`
- `render_obsidian`
- `full_cycle`

step 定义见 [knowledge_workflows.py](/Users/suai/work/config/mac-bootstrap/template/agent/data-hub/knowledge_workflows.py)。

## 当前实现 vs 下一阶段

当前这份 `template/agent/data-hub/` 文档按共享 knowledge root 解释系统边界，但代码层还在分阶段演进：

- 共享 knowledge root、`llm_wiki` ownership、Obsidian 降级：已作为文档边界定稿
- source bucket 的真实路径：仍由 runtime config 控制
- `llm_wiki` API client / context packet / retrieval merge：属于下一阶段实现

阅读顺序：

1. 先按 [CONTEXT.md](./CONTEXT.md) 理解系统模型
2. 再按 [docs/ops.md](./docs/ops.md) 跑当前实现
3. 最后在实现演进时对照 [docs/reference.md](./docs/reference.md) 校对 runtime config 与 source bucket
