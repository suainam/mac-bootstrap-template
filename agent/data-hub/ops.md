# Data Hub 日常运维

> 参考：[README.md](README.md) 架构概览，[reference.md](reference.md) 目录约定与环境变量，[troubleshooting.md](troubleshooting.md) 故障排查。

## 快速入口

| 任务 | 命令 |
|------|------|
| 一键跑完整链路 | `bash .agents/skills/knowledge-source-ingestion/scripts/run-full-cycle.sh "$HOME/work/config/mac-bootstrap" $(date +%F)` |
| 手动补跑日报 | 见下方第 1 节 |
| 重刷日志入库 | 见下方第 2 节 |
| 查看数据库 | `sqlite3 "$HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db" ".tables"` |

## 1. 手动补跑日报

```bash
cd ~/work/config/mac-bootstrap/template/agent/data-hub
source ~/work/config/mac-bootstrap/.venv/bin/activate
export $(grep -v '^#' ../../../private/agent/.obsidian_daily.env | xargs)
python3 daily_summary.py 2026-07-02
```

说明：参数直接传日期，格式 `YYYY-MM-DD`。

## 2. 手动重刷日志入库

```bash
cd ~/work/config/mac-bootstrap/template/agent/data-hub
source ~/work/config/mac-bootstrap/.venv/bin/activate
export $(grep -v '^#' ../../../private/agent/.obsidian_daily.env | xargs)
python3 ingest_logs.py
```

## 3. 查看数据库

```bash
sqlite3 ~/work/config/mac-bootstrap/private/agent/data/agent_history.db \
  "SELECT session_id, timestamp, role, substr(content, 1, 80) FROM messages ORDER BY id DESC LIMIT 10;"
```

## 4. 手动导入外部文件

```bash
cd $HOME/work/config/mac-bootstrap
python3 template/agent/data-hub/ingest_sources.py
```

常用检查：

```bash
sqlite3 $HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db \
  "SELECT source_type, title, path FROM source_documents ORDER BY captured_at DESC;"

sqlite3 $HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db \
  "SELECT item_type, title, substr(content, 1, 100) FROM extracted_items ORDER BY rowid DESC LIMIT 20;"
```

支持的外部文件：`Meetings/*.md`、`Mindmaps/*.xmind`、`Wiki-Clips/*.md`、`Wiki-Clips/*.pdf`、`Wiki-Clips/*.html`

## 5. 生成候选知识清单

```bash
cd $HOME/work/config/mac-bootstrap
template/.venv/bin/python template/agent/data-hub/generate_candidates.py 2026-07-04
```

常用检查：

```bash
sqlite3 $HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db \
  "SELECT candidate_type, status, COUNT(*) FROM knowledge_candidates GROUP BY candidate_type, status ORDER BY candidate_type, status;"
```

输出：`~/work/knowledge/60_Inbox/Candidates/YYYY-MM-DD.md`。审核方式：把 `- review_action: pending` 改成 `accept` / `reject` / `merge` / `defer`。

## 6. 应用轻量审核并落地

```bash
cd $HOME/work/config/mac-bootstrap
template/.venv/bin/python template/agent/data-hub/materialize_candidates.py 2026-07-04
```

常用检查：

```bash
sqlite3 $HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db \
  "SELECT candidate_type, status, materialized_path, title
   FROM knowledge_candidates
   WHERE candidate_date = '2026-07-04'
   ORDER BY candidate_type, status, rowid;"
```

落地规则：`daily` → 日报 `## 候选事项`，`adr` → `40_Knowledge/ADR/`，`card` → `40_Knowledge/Cards/`

## 7. 一键跑完整链路

```bash
cd $HOME/work/config/mac-bootstrap
bash .agents/skills/knowledge-source-ingestion/scripts/run-full-cycle.sh \
  $HOME/work/config/mac-bootstrap \
  2026-07-04
```

加上候选物化（当天已人工审核完）：

```bash
APPLY_REVIEWED=1 bash .agents/skills/knowledge-source-ingestion/scripts/run-full-cycle.sh \
  $HOME/work/config/mac-bootstrap \
  2026-07-04
```

## 8. 回归测试与 2.0 seam 验收

```bash
cd $HOME/work/config/mac-bootstrap/template
UV_CACHE_DIR=.uv-cache uv run pytest \
  tests/test_data_hub.py \
  tests/test_data_hub_sources.py \
  tests/test_candidate_review.py \
  tests/test_materialization.py \
  tests/test_daily_workflows.py \
  -q
```

关键回归点：HTML wiki adapter 抽取、日期归因策略、重跑不冲掉审核状态、孤儿候选清理、materialization 幂等性、workflow seam 结构化输出。

Workflow dry-run：

```bash
cd $HOME/work/config/mac-bootstrap/template
.venv/bin/python agent/data-hub/knowledge_workflows.py daily_ingest_and_review 2026-07-04 --dry-run
.venv/bin/python agent/data-hub/knowledge_workflows.py daily_promote_and_summary 2026-07-04 --dry-run
.venv/bin/python agent/data-hub/knowledge_workflows.py weekly_hygiene_and_reuse 2026-07-04 --dry-run
.venv/bin/python agent/data-hub/knowledge_workflows.py source_adapter_upgrade 2026-07-04 --dry-run
```

## 9. 晨间脚本验证

```bash
cd $HOME/work/config/mac-bootstrap/template/agent/data-hub
bash daily_morning.sh
```

验证点：是否生成今日日报、是否迁移上一工作日 `明日计划`、Obsidian 模板是否正确展开。
