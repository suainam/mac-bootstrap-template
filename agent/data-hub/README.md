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
- [docs/archive/upgrade-plan.md](./docs/archive/upgrade-plan.md) — 历史升级设计稿
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

## Live Record Contract

实时写入不直接落到 `data-hub` 内部脚本，而是走 `knowledge-record` skill 的 live record contract。

- `knowledge-lifecycle-manager record` 是统一入口，用来把当前 agent 会话中的确认知识写入 SQLite
- `knowledge-record` 负责 suggest / confirm / persist 的 live push contract
- `data-hub` 后续 workflow 只消费这些已确认记录，不绕过该 contract 直接写库

## Knowledge Root 边界

`<knowledge-root>` 是共享 knowledge root。

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
  run --workflow build_daily_summary --date 2026-07-09
```

当前 template 内已落地的 workflow 名称：

- `build_daily_summary`
- `build_weekly_summary`
- `build_monthly_summary`
- `build_quarterly_summary`
- `build_yearly_summary`

step 定义见 [knowledge_workflows.py](./knowledge_workflows.py)。

周期总结入口：

```bash
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_daily_summary --date 2026-07-09

template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_weekly_summary --date 2026-07-09
```

人工晋升入口：

```bash
template/.venv/bin/python template/agent/data-hub/scripts/promote_summary_knowledge.py \
  ~/work/knowledge/70_Summaries/Weekly/2026-W28.md \
  --selections-json selections.json
```

## 当前实现边界

已落地：

- 共享 knowledge root、`llm_wiki` ownership、Obsidian 降级
- source bucket 默认 `raw/sources/*`
- `llm_wiki` API client / context packet / retrieval merge
- `70_Summaries` 周/月/季/年自动生成与 lineage
- summary 到 `40_Knowledge` 的人工晋升 gate

不做：

- 不让 `data-hub` 写 `wiki/`
- 不让 summary 自动回流 `llm_wiki`
- 不把旧 `10_Periodic/Weekly|Monthly|Quarterly|Yearly` dataview 目录当作新产物

阅读顺序：

1. 先按 [CONTEXT.md](./CONTEXT.md) 理解系统模型
2. 再按 [docs/ops.md](./docs/ops.md) 跑当前实现
3. 最后在实现演进时对照 [docs/reference.md](./docs/reference.md) 校对 runtime config 与 source bucket
