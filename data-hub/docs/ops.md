# Data Hub 日常运维

> 参考：[README.md](../README.md) 总览，[CONTEXT.md](../CONTEXT.md) 系统边界，[reference.md](reference.md) runtime config 与 source bucket，[troubleshooting.md](troubleshooting.md) 故障排查。

## 快速入口

| 任务 | 命令 |
|------|------|
| 晚间 summary schedule（自动） | `bash template/data-hub/run-daily-evening.sh` |
| 手动补跑指定日期 | 见下方第 1 节 |
| 查看执行状态 | `template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py status --date 2026-07-04` |
| 健康检查 | `template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py health` |
| SQLite 备份 | `template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py backup --date 2026-07-04` |
| 生成周报/月报/季报/年报 | 见下方第 8 节 |
| 查看候选审核结果 | `sqlite3 $AGENT_DB_PATH "SELECT candidate_date, status, COUNT(*) FROM knowledge_candidates GROUP BY candidate_date, status"` |
| 重刷日志入库 | 见下方第 2 节 |
| 查看数据库 | `sqlite3 "$HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db" ".tables"` |
| 新机隔离验收 | 见下方第 10 节 |

## 1. 手动补跑指定日期

```bash
cd ~/work/config/mac-bootstrap

template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_daily_summary --date 2026-07-02
```

说明：

- 日期格式 `YYYY-MM-DD`
- `run` 必须显式指定 `--workflow`，避免误触发废弃的历史链路
- 这里列的是 summary lifecycle workflow；周期总结 workflow 见第 8 节
- 系统心智模型请优先看 [CONTEXT.md](../CONTEXT.md)，不要把 workflow 名称当成唯一架构描述

失败恢复：

```bash
template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  status --date 2026-07-02

template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_daily_summary --date 2026-07-02 --retry-failed <run_id>

template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_daily_summary --date 2026-07-02 --resume <run_id> --from-step build-daily-summary
```

## 2. 手动重刷日志入库

```bash
cd ~/work/config/mac-bootstrap/template/data-hub
source ~/work/config/mac-bootstrap/template/.venv/bin/activate
test -f ../../private/agent/data_hub.runtime.jsonc
python3 scripts/ingest_logs.py
```

## 3. 查看数据库

```bash
sqlite3 ~/work/config/mac-bootstrap/private/agent/data/agent_history.db \
  "SELECT session_id, timestamp, role, substr(content, 1, 80) FROM messages ORDER BY id DESC LIMIT 10;"
```

## 4. 手动导入外部文件

```bash
cd $HOME/work/config/mac-bootstrap
python3 template/data-hub/scripts/ingest_sources.py
```

常用检查：

```bash
sqlite3 $HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db \
  "SELECT source_type, title, path FROM source_documents ORDER BY captured_at DESC;"

sqlite3 $HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db \
  "SELECT item_type, title, substr(content, 1, 100) FROM extracted_items ORDER BY rowid DESC LIMIT 20;"
```

支持的外部文件类型取决于 `sources.inputs` 配置。当前 template 默认适配：

- meeting markdown
- mindmap xmind
- wiki markdown
- wiki pdf
- wiki html

### `llm_wiki` 使用原则

如果 knowledge root 已接入 `llm_wiki`：

- 把它当作 source/wiki intelligence layer，不当作 data-hub workflow owner
- 先在 `llm_wiki` 里找 source、summary、graph、review 线索，再决定是否导入 candidate
- 导入必须走 data-hub 的 candidate / review / materialization 路径
- 不要让 `llm_wiki` 直接改 `60_Inbox/Candidates/*.md`、ADR/Card/Daily 或 SQLite accepted state
- 不要把 `wiki/` 当作 data-hub render 输出目录

本机连通验证：

```bash
python3 - <<'PY'
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:19828/api/v1/health", timeout=5).read().decode())
PY
```

如果 `GET /api/v1/projects` 返回 401，说明 llm_wiki protected API 已开启但 token 尚未配置。到 llm_wiki Settings -> API + MCP 生成 token 后，设置 `LLM_WIKI_TOKEN` 或写入 private runtime 的 `llm_wiki.token`。

## 5. 生成候选知识清单

```bash
cd $HOME/work/config/mac-bootstrap
template/.venv/bin/python template/data-hub/scripts/generate_candidates.py 2026-07-04
```

常用检查：

```bash
sqlite3 $HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db \
  "SELECT candidate_type, status, COUNT(*) FROM knowledge_candidates GROUP BY candidate_type, status ORDER BY candidate_type, status;"
```

输出：`~/work/knowledge/60_Inbox/Candidates/YYYY-MM-DD.md`

## 6. 应用审核并落地

```bash
cd $HOME/work/config/mac-bootstrap
template/.venv/bin/python template/data-hub/scripts/materialize_candidates.py 2026-07-04
```

常用检查：

```bash
sqlite3 $HOME/work/config/mac-bootstrap/private/agent/data/agent_history.db \
  "SELECT candidate_type, status, materialized_path, title
   FROM knowledge_candidates
   WHERE candidate_date = '2026-07-04'
   ORDER BY candidate_type, status, rowid;"
```

落地规则：`daily` -> 日报，`adr` -> `40_Knowledge/ADR/`，`card` -> `40_Knowledge/Cards/`

## 7. 手动生成 daily summary

```bash
cd $HOME/work/config/mac-bootstrap
template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_daily_summary --date 2026-07-04
```

运行结果会写入 `workflow_runs` / `workflow_steps`，每步日志在 `private/agent/data/runs/<run_id>/`。

## 8. 生成周期总结

所有周期总结仍通过 `knowledge-lifecycle-manager` 入口，不直接绕过 lifecycle：

```bash
cd $HOME/work/config/mac-bootstrap

template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_daily_summary --date 2026-07-09

template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_weekly_summary --date 2026-07-09

template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_monthly_summary --date 2026-07-09

template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_quarterly_summary --date 2026-07-09

template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_yearly_summary --date 2026-07-09
```

输出位置：

```text
~/work/knowledge/70_Summaries/{Daily,Weekly,Monthly,Quarterly,Yearly}/
```

其中 `70_Summaries/Daily` 是 weekly 的上一层输入；weekly/monthly/quarterly/yearly 生成前会检查上一层完整性，并按部署日起截断补齐，避免回填部署前不存在的日期。

summary 是 quarantine 半成品层，默认不进入 `llm_wiki` 索引，也不会自动晋升到 `40_Knowledge/`。需要晋升时，人工挑选条目后运行：

```bash
template/.venv/bin/python template/data-hub/scripts/promote_summary_knowledge.py \
  ~/work/knowledge/70_Summaries/Weekly/2026-W28.md \
  --selections-json selections.json
```

## 9. 回归测试

```bash
cd $HOME/work/config/mac-bootstrap/template
UV_CACHE_DIR=.uv-cache uv run pytest \
  tests/test_data_hub.py \
  tests/test_data_hub_sources.py \
  tests/test_candidate_review.py \
  tests/test_materialization.py \
  tests/archive/test_phase4_weekly_summary.py \
  tests/test_daily_summary_runtime.py \
  tests/test_ingest_logs_runtime.py \
  tests/test_claim_extraction.py \
  tests/test_auto_review.py \
  tests/test_hygiene_audit.py \
  -q
```

Workflow dry-run：

```bash
cd $HOME/work/config/mac-bootstrap/template
.venv/bin/python data-hub/knowledge_workflows.py build_daily_summary 2026-07-04 --dry-run
.venv/bin/python data-hub/knowledge_workflows.py build_weekly_summary 2026-07-10 --dry-run
```

## 10. 晨间脚本验证

```bash
cd $HOME/work/config/mac-bootstrap/template/data-hub
bash daily_morning.sh
```

## 11. 新机隔离验收

目的：完整跑通 Data Hub lifecycle，但不读取真实 vault、真实 agent 日志、真实 private DB 或外部 LLM 服务。

如果当前环境已切 shared-root，可把 fixture source bucket 放在临时 vault 的 `raw/sources/...`，并通过 runtime config 或显式环境变量指向它；不要依赖 legacy `50_Sources/*` 默认值。
