# Data Hub 日常运维

> 参考：[README.md](README.md) 架构概览，[reference.md](reference.md) 目录约定与环境变量，[troubleshooting.md](troubleshooting.md) 故障排查。

## 快速入口

| 任务 | 命令 |
|------|------|
| 晚间全链路（自动） | `bash template/agent/data-hub/run-daily-evening.sh` |
| 手动补跑指定日期 | 见下方第 1 节 |
| 查看执行状态 | `template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py status --date 2026-07-04` |
| 健康检查 | `template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py health` |
| SQLite 备份 | `template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py backup --date 2026-07-04` |
| 查看候选审核结果 | `sqlite3 $AGENT_DB_PATH "SELECT candidate_date, status, COUNT(*) FROM knowledge_candidates GROUP BY candidate_date, status"` |
| 重刷日志入库 | 见下方第 2 节 |
| 查看数据库 | `sqlite3 "$HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db" ".tables"` |

## 1. 手动补跑指定日期

```bash
cd ~/work/config/mac-bootstrap

# 补跑全链路
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow full_cycle --date 2026-07-02

# 或跑命名 workflow
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow daily_ingest_and_review --date 2026-07-02
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow daily_promote_and_summary --date 2026-07-02

# 或保留旧别名
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py --review-only --date 2026-07-02
```

说明：参数直接传日期，格式 `YYYY-MM-DD`。

失败恢复：

```bash
# 查看 run_id 和失败 step
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  status --date 2026-07-02

# 从第一个 failed step 继续
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow full_cycle --date 2026-07-02 --retry-failed <run_id>

# 从指定 step 继续
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow full_cycle --date 2026-07-02 --resume <run_id> --from-step knowledge-materialization
```

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
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow full_cycle --date 2026-07-04
```

运行结果会写入 `workflow_runs` / `workflow_steps`，每步日志在
`private/agent/data/runs/<run_id>/`。

## 8. 回归测试与 2.0 seam 验收

```bash
cd $HOME/work/config/mac-bootstrap/template
UV_CACHE_DIR=.uv-cache uv run pytest \
  tests/test_data_hub.py \
  tests/test_data_hub_sources.py \
  tests/test_candidate_review.py \
  tests/test_materialization.py \
  tests/test_phase4_weekly_summary.py \
  tests/test_daily_summary_runtime.py \
  tests/test_ingest_logs_runtime.py \
  tests/test_claim_extraction.py \
  tests/test_auto_review.py \
  tests/test_hygiene_audit.py \
  -q
```

生命周期覆盖：source ingest → claim extract → auto review → materialize → daily/weekly synthesis → hygiene audit（共 7 个环节，85 个测试）。

关键回归点：HTML wiki adapter 抽取、日期归因策略、重跑不冲掉审核状态、孤儿候选清理、materialization 幂等性、置信度阈值边界（daily/card 0.8，adr 0.85）、hygiene audit 孤儿/重复/broken materialization 检测。

Workflow dry-run：

```bash
cd $HOME/work/config/mac-bootstrap/template
.venv/bin/python agent/data-hub/knowledge_workflows.py daily_ingest_and_review 2026-07-04 --dry-run
.venv/bin/python agent/data-hub/knowledge_workflows.py daily_promote_and_summary 2026-07-04 --dry-run
.venv/bin/python agent/data-hub/knowledge_workflows.py weekly_hygiene_and_reuse 2026-07-04 --dry-run
.venv/bin/python agent/data-hub/knowledge_workflows.py source_adapter_upgrade 2026-07-04 --dry-run
.venv/bin/python agent/data-hub/knowledge_workflows.py full_cycle 2026-07-04 --dry-run
```

## 9. 晨间脚本验证

```bash
cd $HOME/work/config/mac-bootstrap/template/agent/data-hub
bash daily_morning.sh
```

验证点：是否生成今日日报、是否迁移上一工作日 `明日计划`、Obsidian 模板是否正确展开。
