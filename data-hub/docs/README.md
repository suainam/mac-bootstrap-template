# Data Hub Docs

`template/data-hub/docs/` 只放专题文档，不重复根目录文件职责。

## 边界

- 根目录 [README.md](../README.md)：给人类的总入口
- 根目录 [CONTEXT.md](../CONTEXT.md)：系统模型、ownership、canonical state
- 根目录 [AGENTS.md](../AGENTS.md)：agent 执行约束
- `docs/`：运维、参考、排障、验收、历史设计

## 现行文档

- [ops.md](./ops.md) — 日常运行、补跑、恢复、回归、隔离验收
- [reference.md](./reference.md) — knowledge root、runtime config、source bucket、canonical/projection 约定
- [troubleshooting.md](./troubleshooting.md) — 常见故障定位路径
- [cron-setup.md](./cron-setup.md) — 现行 launchd 09:00 / 17:30 / 18:00 调度与可选 Cron fallback
- [summary-engine-implementation-report.md](./summary-engine-implementation-report.md) — 分阶段提交、复审修复、五层 E2E 与最终门禁证据

## 历史与实施证据

- [2026-07-10-summary-engine-design.md](./2026-07-10-summary-engine-design.md) — 已实施的 Summary Engine 设计基线，不作为运行手册
- [2026-07-10-summary-engine-implementation-plan.md](./2026-07-10-summary-engine-implementation-plan.md) — 已执行的 TDD 计划，不作为待办清单
- [archive/acceptance-report-2026-07-05.md](./archive/acceptance-report-2026-07-05.md) — 旧 workflow 的真实验收快照
- [archive/cron-setup-legacy.md](./archive/cron-setup-legacy.md) — 已被 launchd 09:00 / 17:30 / 18:00 链替代的旧 Codex Cron 方案
- [archive/upgrade-plan.md](./archive/upgrade-plan.md) — 历史设计草案

## 维护规则

- 稳定系统事实先更新 `CONTEXT.md`
- 人类入口变化先更新 `README.md`
- `docs/` 里的专题文档只写各自主题，不复制系统总模型
- 历史文档若保留旧路径或旧流程，必须放入 `archive/` 或在文件开头显式标注“历史上下文”
