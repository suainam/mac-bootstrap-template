# Agent Data Hub 运维手册

把 Agent 对话、Git 活动和外部材料（会议纪要/Wiki/XMind）汇总成可追溯的日报与知识沉淀流水线。

**文档导航**：
- [docs/ops.md](docs/ops.md) — 日常运维命令
- [docs/reference.md](docs/reference.md) — 目录约定、环境变量、Obsidian 插件、幂等性约定
- [docs/troubleshooting.md](docs/troubleshooting.md) — 故障排查
- [docs/acceptance-report.md](docs/acceptance-report.md) — 真实本机验收报告
- [docs/upgrade-plan.md](docs/upgrade-plan.md) — 目标设计稿
- [docs/cron-setup.md](docs/cron-setup.md) — cron/定时任务参考

根目录保留 Python workflow 模块、shell 入口、schema、配置样例和 README；一线运维、阶段总结、验收报告、升级设计等支持材料统一放在 `docs/`，LLM 提示词统一放在 `prompts/`。

## 当前架构

边界约定：

- `SQLite` 是事件账本，保存原始日志和结构化结果
- `Obsidian Vault` 是展示层和人工编辑层
- `data-hub` 脚本负责采集、汇总、写回，不直接充当知识库

数据来源分两条路径：

**Pull 路径**（主流水线）—— 从 agent 日志和外部材料中自动发现知识：

```
1. preflight retrieve  →  knowledge_retrieval.py
2. source ingest       →  ingest_logs.py + ingest_sources.py
3. claim extract       →  claim_extraction.py
4. candidate review    →  generate_candidates.py
5. materialize         →  materialize_candidates.py
6. daily synthesis     →  daily_summary.py
7. hygiene audit       →  hygiene_audit.py
```

**Push 路径**（手动记录）—— agent 在对话中直接写入知识：

```
agent (knowledge-record skill)  →  record_knowledge.py
                                    ↓
                              knowledge_records (status=accepted)
                                    ↓
                              materialize_candidates.py (nightly)
```

Push 路径不走 classification / llm_filter / auto_review，写入即 accepted。详见 [`docs/data-hub-record-knowledge.md`](../../docs/data-hub-record-knowledge.md)。

## Workflow 入口

对外统一入口是 `knowledge-lifecycle-manager`：

```bash
cd $HOME/work/config/mac-bootstrap
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py run --workflow full_cycle --date $(date +%F)
```

底层由 `knowledge_workflows.py` 维护标准 workflow registry：

| Workflow | Skills |
|----------|--------|
| `daily_ingest_and_review` | reuse-retrieval → source-ingestion → claim-extraction → candidate-review |
| `daily_promote_and_summary` | materialization → daily-weekly-synthesis |
| `weekly_hygiene_and_reuse` | hygiene-audit → reuse-retrieval |
| `source_adapter_upgrade` | source-ingestion + regression tests |
| `auto_review_only` | auto_review |
| `materialize_only` | materialize |
| `full_cycle` | ingest_and_review → auto_review → promote_and_summary |

Dry-run 验证：

```bash
cd $HOME/work/config/mac-bootstrap/template
.venv/bin/python agent/data-hub/knowledge_workflows.py daily_ingest_and_review $(date +%F) --dry-run
```

工业化运行默认使用 durable runner：每次运行生成 `run_id`，写入
`workflow_runs` / `workflow_steps`，并把每步 stdout/stderr 落盘到
`private/agent/data/runs/<run_id>/`。失败后可按 run_id 恢复：

```bash
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow full_cycle --date 2026-07-04 --retry-failed <run_id>
```

## 组件职责速查

| 脚本 | 职责 |
|------|------|
| `ingest_logs.py` | 采集 Claude/Codex/Gemini 日志 → SQLite sessions/messages |
| `ingest_sources.py` | 外部材料（meeting/wiki/xmind）→ source_documents/chunks/items |
| `claim_extraction.py` | source items + assistant chat responses → claim_packets + evidence_links |
| `generate_candidates.py` | extracted_items + assistant response claims → knowledge_candidates + 60_Inbox/Candidates/YYYY-MM-DD.md |
| `auto_review.py` | 外部材料候选按置信度阈值自动审核；chat response candidates 保持 pending |
| `materialize_candidates.py` | 读审核动作 + 读 `knowledge_records` → 落地 ADR/Card/日报插入 |
| `record_knowledge.py` | Push 路径入口：agent 写 knowledge_records（status=accepted，跳过 pipeline） |
| `daily_summary.py` | 日期粒度 → LLM 摘要写回 Obsidian 日报 |
| `hygiene_audit.py` | 审计孤儿候选/过期条目/重复落地（只读，不修复） |
| `knowledge_retrieval.py` | 任务前预检索 → retrieval_packet |
| `knowledge_workflows.py` | workflow registry（实现层） |
| `workflow_runner.py` | durable workflow 状态、日志、重试、恢复 |
| `knowledge-lifecycle-manager` | 统一入口（运行 / 状态 / 健康检查） |
| `daily_morning.sh` | 晨间自动建日报 + 迁移昨日计划 |
| `run-daily-evening.sh` | 晚间全链路 manager adapter |

**公用模块**：
- `execution_logger.py` — 执行日志记录类，写 execution_log 表
- `db_helper.py` — DB 连接与常用查询封装
- `obsidian_helper.py` — Obsidian vault 读写（日报/周报）
- `date_utils.py` — 工作日判断、周范围计算（chinese-calendar）

## Skill 对应关系

8 个 knowledge-* skills 位于 `template/agent/skills/personal/`。其中 7 个 project-scoped（仅 mac-bootstrap 项目内可用），1 个 global-scoped（全项目可用）：

**Pull 路径（project-scoped）：**
- `knowledge-source-ingestion`
- `knowledge-reuse-retrieval`
- `knowledge-claim-extraction`
- `knowledge-candidate-review`
- `knowledge-materialization`
- `knowledge-daily-weekly-synthesis`
- `knowledge-hygiene-audit`

**Push 路径（global-scoped）：**
- `knowledge-record` — 对话中直接写入 `knowledge_records` 表，跳过 pipeline

## 当前状态

已跑通全链路：assistant chat responses / meetings / xmind / wiki pdf → SQLite → candidates → daily summary → Obsidian

Chat-derived candidates 的边界：只从 agent/assistant 回复中提炼建议、方案、决策、风险和后续动作；用户提问只写入候选 metadata 的 `background_prompt`，用于审核上下文，不单独生成候选。旧版 `chat_message/chat-claim-v1` 用户提问投影会在重建候选时清理；新版来源为 `chat_response/chat-answer-v2`，并且始终跳过自动审核。

待增强：HTML table/callout 细结构、claims/evidence 证据链模型、OCR fallback、source family 扩展。

## 新机前置依赖

最小可用环境：

| 依赖 | 用途 | 验收命令 |
|------|------|----------|
| Python 3.13+ | 运行 data-hub 脚本和 pytest | `python3 --version` |
| template venv | 仓库维护的稳定 Python runtime | `template/.venv/bin/python --version` |
| uv | 创建/维护 venv，备用运行 pytest | `uv --version` |
| sqlite3 CLI | 人工检查账本和验收 SQL | `sqlite3 --version` |
| make | 运行仓库门禁 | `make check` |
| agy 或 claude CLI | `daily_summary.py` 的 LLM 摘要来源 | `agy --help` 或 `claude --help` |

注意事项：

- 测试和生产脚本优先使用 `template/.venv/bin/python`，不要临时切到父仓库 `.venv`。
- 统一运行配置为 `private/agent/data_hub.runtime.jsonc`，公开样例见 `template/agent/data-hub/data_hub.runtime.jsonc.example`。它集中管理 paths、source inputs、agent log dirs、LLM backends 和 workflow 默认值。
- 配置优先级：显式 shell 环境变量 > `data_hub.runtime.jsonc` > 代码默认值。不要再新增 `.env` 或 LLM-only 配置文件。
- 新机器没有 Claude/Codex/AGY 历史日志目录时，`ingest_logs.py` 应返回 0 条记录并继续，而不是失败。
- 没有真实 LLM CLI 或不想调用外部服务时，可以在隔离验收里用临时 `PATH` 注入 fake `agy`；真实运行时应配置 `agy` 或 `claude`。

## 隔离实机验收

目标：在不读取真实 `~/work/knowledge`、真实 agent 日志或 private secrets 的前提下，证明 full lifecycle 可在新机器上跑通。

1. 创建临时 HOME、vault、DB、runs、git roots 和 fake `agy`。
2. 在临时 vault 写入最小 source fixture：
   - `50_Sources/Meetings/YYYY-MM-DD_*.md`
   - `50_Sources/Wiki-Clips/YYYY-MM-DD_*.md`
3. 设置隔离环境。注意先保存 `REPO`，再覆盖 `HOME`：

```bash
export ACCEPT=/tmp/data-hub-acceptance
export REPO=$HOME/work/config/mac-bootstrap
export HOME=$ACCEPT/home
export OBSIDIAN_VAULT_DIR=$ACCEPT/vault
export OBSIDIAN_DAILY_DIR=10_Periodic/Daily
export AGENT_DB_PATH=$ACCEPT/agent_history.db
export AGENT_RUNS_DIR=$ACCEPT/runs
export GIT_SEARCH_ROOTS=$ACCEPT/git-roots
export PATH=$ACCEPT/bin:$PATH
cd "$REPO"
```

4. 执行 dry-run 和 durable full cycle：

```bash
template/.venv/bin/python template/agent/data-hub/knowledge_workflows.py full_cycle 2026-07-04 --dry-run

template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow full_cycle --date 2026-07-04 --run-id acceptance_clean
```

5. 验收证据：

```bash
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py status --date 2026-07-04
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py candidates 2026-07-04
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py health
sqlite3 "$AGENT_DB_PATH" \
  "SELECT COUNT(*) FROM source_documents; SELECT COUNT(*) FROM knowledge_candidates; SELECT COUNT(*) FROM artifact_manifest;"
find "$OBSIDIAN_VAULT_DIR" -maxdepth 5 -type f | sort
```

2026-07-05 本机验收记录：

- 依赖：`python3 3.13.13`，`template/.venv/bin/python 3.13.13`，`uv 0.11.26`，`sqlite3 3.51.0`。
- 基线测试：Data Hub 相关 pytest `115 passed`。
- 恢复路径：第一次 `acceptance_full` 暴露出空日志目录 bug；修复后 `--retry-failed acceptance_full` 从失败 step 继续，8 步最终 completed。
- 干净路径：`acceptance_clean` 在全新临时目录中 8/8 completed，`manager.py health` 返回 `All clear`。
- 干净路径产物计数：`source_documents=2`，`document_chunks=7`，`extracted_items=7`，`knowledge_candidates=6`，`artifact_manifest=16`。
- 候选结果：`daily accepted=3`，`card accepted=1`，`adr pending=2`。
- vault 产物：`10_Periodic/Daily/2026-07-04.md`、`60_Inbox/Candidates/2026-07-04.md`、`40_Knowledge/Cards/*.md`。
- 备份命令：`manager.py backup --date 2026-07-04` 生成 SQLite 备份并记录 sha256。

## 测试

**虚拟环境**：pytest 必须使用 `template/` 下的 venv，**不是** repo 根目录的 `.venv`。

```bash
# 正确：进 template/ 再用 .venv
cd $HOME/work/config/mac-bootstrap/template
.venv/bin/python -m pytest tests/ -q

# 或从仓库根调用（指定完整路径）
cd $HOME/work/config/mac-bootstrap
template/.venv/bin/python -m pytest template/tests/ -q
```

> `uv` 等价写法（template/ 目录内）：
> ```bash
> cd $HOME/work/config/mac-bootstrap/template
> UV_CACHE_DIR=.uv-cache uv run pytest tests/ -q
> ```

**当前覆盖**（覆盖率 ≥ 80%）：

| 测试文件 | 覆盖环节 |
|---------|---------|
| `test_data_hub.py` | SQLite schema / 连接 |
| `test_data_hub_sources.py` | source adapters / ingest |
| `test_ingest_logs_runtime.py` | ingest_logs runtime |
| `test_candidate_review.py` | generate_candidates |
| `test_materialization.py` | materialize_candidates |
| `test_daily_summary_runtime.py` | daily_summary |
| `test_phase4_weekly_summary.py` | weekly_summary |
| `test_claim_extraction.py` | claim_extraction（环节 3） |
| `test_auto_review.py` | auto_review 阈值边界（环节 4） |
| `test_hygiene_audit.py` | hygiene_audit 全检测项（环节 7） |
