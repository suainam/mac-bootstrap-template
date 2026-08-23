# Bootstrap

Use this branch when the project lacks durable Agent guidance or knowledge routing.

## Discover before proposing

1. Inventory existing rules, human docs, domain docs, decisions, operations docs, plans, generated projections, catalogs, schemas, configuration, tests, and tracker guidance through project-declared tools. Reuse code graphs, Git ignore semantics, package manifests, Make targets, and repository test entrypoints before fallback discovery.
2. Extract only project-specific facts that code does not make reliably obvious: red lines, authority boundaries, critical commands, domain distinctions, safety constraints, and known traps.
3. Label each extraction as verified fact, repeated-pattern candidate, or unresolved judgment. Cite the current source.
4. Ask for the smallest decisions that change authority, risk, or meaning. Keep other uncertainty visible.

## Default ownership fallback

Use only when existing project rules do not define an owner.

| Knowledge Surface | Default Authority | Strict Responsibility | Anti-Mixing Redlines (严禁混写红线) |
|---|---|---|---|
| Human Purpose & Quickstart | `README.md` | Human onboarding, 5-min quickstart, layout overview. Keep thin (< 100 lines). | 严禁堆砌长篇业务协议、Agent 内部 Prompt、或详细运维 Runbook。 |
| System Architecture (SSOT) | `CONTEXT.md` | Single source of truth for mental model, domain vocabulary, data flow, authority ownership. | 严禁写日常流水账、逐步操作教程或临时任务计划。 |
| Agent Action Policy & Redlines | `AGENTS.md` / `CLAUDE.md` | Negative boundaries, critical check commands, validation gates, routing. Keep tight (< 80 lines). Sibling parity mandatory. | 严禁抄录系统架构描述、代码细节或冗长操作手册；严禁跨层级重复导入全局规则。 |
| Deep Knowledge & Runbooks | `docs/` | Step-by-step runbooks, troubleshooting guides, API contracts, ADR collection. | 严禁 Agent 顶层全量常驻加载；必须按需检索读取。严禁在 `docs/` 外设立并行的 `wiki/` 沼泽。 |
| Temporary Work & Specs | Issue tracker / PRD | Ephemeral task plans, tickets, acceptance criteria. | 临时计划完成后及时归档/清理，不沉淀为伪长期文档。 |
| Structured Facts | Config, schema, code | Machine-readable schemas, type contracts, test fixtures. | 结构化事实以代码和 schema 为准，文档只做引用。 |
Use Markdown links between explanatory documents. Use filesystem symlinks only for compatibility files that must be byte-identical.

## Loading budgets

Use the budgets emitted by `scripts/audit_project.py`; it is the single mechanical authority for limits and measurements. Treat on-demand and human documents by responsibility, and propose a semantic split only when one document owns multiple stable responsibilities.

Split by audience or stable responsibility. Keep each routed fact only at its owner; an index names the owner without restating its contents.

## Minimal scaffold rule

Create only files justified by observed project needs. A small library may need one human entry and one Agent authority. Add context, ADRs, or operations docs only when the corresponding stable knowledge exists. Present the ownership matrix and patch before writing.

Bootstrap is complete when a new Agent can find the correct authority without repository-wide search, every generated statement has evidence, and persistent budgets pass.
