# Data Hub Docs

`template/agent/data-hub/docs/` 只放专题文档，不重复根目录文件职责。

## 边界

- 根目录 [README.md](../README.md)：给人类的总入口
- 根目录 [CONTEXT.md](../CONTEXT.md)：系统模型、ownership、canonical state
- 根目录 [AGENTS.md](../AGENTS.md)：agent 执行约束
- `docs/`：运维、参考、排障、验收、历史设计

## 文档索引

- [ops.md](./ops.md) — 日常运行、补跑、恢复、回归、隔离验收
- [reference.md](./reference.md) — knowledge root、runtime config、source bucket、canonical/projection 约定
- [troubleshooting.md](./troubleshooting.md) — 常见故障定位路径
- [acceptance-report.md](./acceptance-report.md) — 2026-07-05 真实本机验收记录，含历史路径样本说明
- [2026-07-10-summary-engine-design.md](./2026-07-10-summary-engine-design.md) — 结构化 Summary Engine、条目级维度、Prompt 契约与幂等设计
- [archive/upgrade-plan.md](./archive/upgrade-plan.md) — 历史设计草案，保留演进背景，不作为当前权威 runbook
- [cron-setup.md](./cron-setup.md) — cron/定时任务参考
- [../../../docs/superpowers/specs/2026-07-09-data-hub-dual-system-design.md](../../../docs/superpowers/specs/2026-07-09-data-hub-dual-system-design.md) — 当前双系统正式设计稿

## 维护规则

- 稳定系统事实先更新 `CONTEXT.md`
- 人类入口变化先更新 `README.md`
- `docs/` 里的专题文档只写各自主题，不复制系统总模型
- 历史文档若保留旧路径或旧流程，必须显式标注“历史上下文”
