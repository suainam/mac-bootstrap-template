# Agent Data Hub 运维手册

把 Agent 对话、Git 活动和外部材料（会议纪要/Wiki/XMind）汇总成可追溯的日报与知识沉淀流水线。

**文档导航**：
- [ops.md](ops.md) — 日常运维命令
- [reference.md](reference.md) — 目录约定、环境变量、Obsidian 插件、幂等性约定
- [troubleshooting.md](troubleshooting.md) — 故障排查
- [upgrade_plan.md](upgrade_plan.md) — 目标设计稿

## 当前架构

边界约定：

- `SQLite` 是事件账本，保存原始日志和结构化结果
- `Obsidian Vault` 是展示层和人工编辑层
- `data-hub` 脚本负责采集、汇总、写回，不直接充当知识库

2.0 主流程：

```
1. preflight retrieve  →  knowledge_retrieval.py
2. source ingest       →  ingest_logs.py + ingest_sources.py
3. claim extract       →  claim_extraction.py
4. candidate review    →  generate_candidates.py
5. materialize         →  materialize_candidates.py
6. daily synthesis     →  daily_summary.py
7. hygiene audit       →  hygiene_audit.py
```

## Workflow 入口

`knowledge_workflows.py` 固化了 4 条编排路径：

| Workflow | Skills |
|----------|--------|
| `daily_ingest_and_review` | reuse-retrieval → source-ingestion → claim-extraction → candidate-review |
| `daily_promote_and_summary` | materialization → daily-weekly-synthesis |
| `weekly_hygiene_and_reuse` | hygiene-audit → reuse-retrieval |
| `source_adapter_upgrade` | source-ingestion + regression tests |

Dry-run 验证：

```bash
cd $HOME/work/config/mac-bootstrap/template
.venv/bin/python agent/data-hub/knowledge_workflows.py daily_ingest_and_review $(date +%F) --dry-run
```

## 组件职责速查

| 脚本 | 职责 |
|------|------|
| `ingest_logs.py` | 采集 Claude/Codex/Gemini 日志 → SQLite sessions/messages |
| `ingest_sources.py` | 外部材料（meeting/wiki/xmind）→ source_documents/chunks/items |
| `claim_extraction.py` | source items + chat → claim_packets + evidence_links |
| `generate_candidates.py` | extracted_items → knowledge_candidates + 60_Inbox/Candidates/YYYY-MM-DD.md |
| `materialize_candidates.py` | 读审核动作 → 落地 ADR/Card/日报插入 |
| `daily_summary.py` | 日期粒度 → LLM 摘要写回 Obsidian 日报 |
| `hygiene_audit.py` | 审计孤儿候选/过期条目/重复落地（只读，不修复） |
| `knowledge_retrieval.py` | 任务前预检索 → retrieval_packet |
| `knowledge_workflows.py` | 4 条编排路径入口 |
| `daily_morning.sh` | 晨间自动建日报 + 迁移昨日计划 |

## Skill 对应关系

7 个 knowledge-* skills 位于 `template/agent/skills/personal/`，project-scoped（仅 mac-bootstrap 项目内可用）：

- `knowledge-source-ingestion`
- `knowledge-reuse-retrieval`
- `knowledge-claim-extraction`
- `knowledge-candidate-review`
- `knowledge-materialization`
- `knowledge-daily-weekly-synthesis`
- `knowledge-hygiene-audit`

## 当前状态

已跑通全链路：chat logs / meetings / xmind / wiki pdf → SQLite → candidates → daily summary → Obsidian

待增强：HTML table/callout 细结构、claims/evidence 证据链模型、OCR fallback、source family 扩展。
