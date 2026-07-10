# Data Hub Agent Rules

先读 [CONTEXT.md](./CONTEXT.md)。

## 修改边界

- Data Hub implementation and subsystem documentation live under `template/data-hub/`.
- Agent Skill source or routing changes belong under `template/agent-skills/`.
- Agent runtime configuration changes belong under `template/agent/`.
- 不把 data-hub 文档写到 `private/` 或仓库其他位置
- 不把本机 secrets、token、私有 API 地址写入 `template/`
- 不把 `wiki/` 当 data-hub render 目标
- 不重新引入 `50_Sources` 作为主目录模型
- 不让 `70_Summaries/` 自动回流 `llm_wiki`
- 不把 `daily` 原文落成 SQLite canonical source

## 修改前先判断

- 人类入口内容 -> `README.md`
- 稳定系统模型 -> `CONTEXT.md`
- agent 执行约束 -> `AGENTS.md`
- 命令/运维/排障/验收 -> `docs/`

## 数据流约束

- SQLite 是 canonical state
- `daily` 是 `llm_wiki` 输入，不是 `data-hub` 原文账本
- `70_Summaries` 是 quarantine projection，不是长期知识
- `llm_wiki` 是 source/wiki layer，不是 accepted knowledge owner
- `data-hub` 决定 candidate/accepted/materialized 状态，不由 `llm_wiki` 直写

## 文档约束

- README 保持薄，只给人类入口
- CONTEXT 负责 ownership、canonical state、层次边界
- docs 负责细节 runbook，不反过来重写系统模型
- 若代码仍有 legacy workflow 名称或 legacy source bucket，文档必须明确“当前实现”和“目标模型”的差异，不能假装已完成
- 若设计涉及 `10_Periodic/Weekly|Monthly|Quarterly|Yearly`，默认视为待删除 legacy 目录，不再新增依赖

## 最小验证

- 至少检查被改文档之间链接和表述一致
- 至少 grep 一遍 `50_Sources` / `llm_wiki` / `raw/sources`，避免新旧叙事冲突
- 至少检查 `70_Summaries` 与 `daily first` 的新模型是否前后一致
- 若文档引用 workflow 名称、目录、脚本，必须以当前 repo 文件为准
