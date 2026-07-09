# Data Hub 故障排查

## 1. 日报没生成

检查顺序：
1. `OBSIDIAN_VAULT_DIR` 是否正确
2. `OBSIDIAN_DAILY_DIR` 是否正确
3. Obsidian periodic-notes 目录是否已迁到 `10_Periodic/Daily`
4. `daily_morning.sh` 是否被 launchd 正常调起

## 2. 摘要写回位置不对

检查顺序：
1. `data_hub.runtime.jsonc` 中 `paths.daily_dir`
2. `daily_summary.py` 中的 `DAILY_DIR`
3. Obsidian 插件配置是否仍残留旧路径

## 3. 总结内容重复或覆盖异常

检查顺序：
1. `obsidian_helper.write_daily_section()` 的替换逻辑
2. 若是旧测试或旧脚本调用，检查 `daily_summary.py` 的兼容函数 `inject_summary_to_daily()`
3. 日报模板中 `## AI 总结` 是否被手工改坏

## 4. 外部材料日期归因不符合预期

检查顺序：
1. 文件名是否以 `YYYY-MM-DD_` 开头
2. `source_documents.captured_at` 是否是首次落库日期
3. `EXTERNAL_SOURCE_DATE_MODE` 是否被改成了 `filename_only`

注意：文件内容中的业务日期**不会**自动成为日报日期。

## 5. 候选审核状态意外丢失

检查顺序：
1. source 内容是否真的发生变化（未变化应直接跳过）
2. `knowledge_candidates` 是否被孤儿清理误删
3. 是否手工修改了 SQLite 或跳过了标准脚本

## 7. 晚间全链路未自动运行

检查顺序：
1. `~/Library/Logs/agent-data-hub/evening.log` 是否有输出
2. launchd job 是否正常加载：`launchctl list | grep daily-evening`
3. plist 时间是否正确：18:00 触发
4. 脚本路径是否正确：`template/agent/data-hub/run-daily-evening.sh`
5. durable run 状态：`manager.py status --date YYYY-MM-DD`

失败恢复：

```bash
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow full_cycle --date YYYY-MM-DD --retry-failed <run_id>
```

## 8. 自动审核结果不符合预期

检查顺序：
1. 查看候选置信度：`sqlite3 $AGENT_DB_PATH "SELECT id, candidate_type, confidence, status FROM knowledge_candidates WHERE candidate_date = 'YYYY-MM-DD'"`
2. 确认阈值：daily 0.8, card 0.8, adr 0.85
3. 查看执行日志：`sqlite3 $AGENT_DB_PATH "SELECT * FROM execution_log WHERE step_name = 'auto_review' AND execution_date = 'YYYY-MM-DD'"`
4. 若阈值需调整，编辑 `auto_review.py` 的 `THRESHOLDS` 常量

## 9. 执行日志查询失败

检查顺序：
1. execution_log 表是否存在：`sqlite3 $AGENT_DB_PATH ".tables" | grep execution_log`
2. schema.sql 是否已应用：`db_helper.get_db_connection()` 自动执行 schema
3. 权限问题：DB 文件是否可写
4. durable 表是否存在：`sqlite3 $AGENT_DB_PATH ".tables" | grep workflow_runs`

## 10. materialize_candidates.py 未找到 auto-accepted 候选

检查顺序：
1. auto_review 是否在 materialize 之前运行
2. 候选状态：`SELECT status, COUNT(*) FROM knowledge_candidates WHERE candidate_date = 'YYYY-MM-DD' GROUP BY status`
3. 执行日志确认步骤顺序：`SELECT step_name, started_at, status FROM execution_log WHERE execution_date = 'YYYY-MM-DD' ORDER BY started_at`

## 11. durable run 卡在 running

检查顺序：
1. `manager.py health` 是否提示 stale runs
2. `manager.py status --date YYYY-MM-DD` 查看最后一个 step
3. 打开 `workflow_steps.stdout_path` / `stderr_path`
4. 若确认进程已结束，使用 `--retry-failed <run_id>` 或 `--resume <run_id> --from-step <step_name>` 补跑

## 12. 新机器没有 agent 日志目录

表现：`ingest_logs.py` 在没有 `~/.claude/projects`、`~/.codex/sessions`、OpenCode 或 AGY 日志目录时应输出 0 条记录并继续。

检查顺序：
1. 是否使用了最新脚本；旧版本可能在 `total_records += count` 处因 `None` 失败
2. `workflow_steps.stderr_path` 是否包含 `unsupported operand type(s) for +=`
3. 修复后用 `--retry-failed <run_id>` 从 `knowledge-source-ingestion:logs` 继续

## 13. 临时 env 没生效或读到了真实 DB/vault

表现：明明设置了 `AGENT_DB_PATH` / `OBSIDIAN_VAULT_DIR`，但 `manager.py status` 看不到临时 run，或读到了真实 private DB。

检查顺序：
1. 命令前是否显式导出了 `AGENT_DB_PATH`、`OBSIDIAN_VAULT_DIR`、`OBSIDIAN_DAILY_DIR`
2. 当前脚本是否使用“shell env 优先，env 文件补默认”的版本
3. 若在隔离验收中覆盖 `HOME`，先保存 `REPO=$HOME/work/config/mac-bootstrap`，再设置临时 `HOME`
4. 用 `sqlite3 "$AGENT_DB_PATH" ".tables"` 确认实际 DB 路径

## 14. `llm_filter` 走不到内网 backend 或意外 fallback 到 CLI

表现：
- `generate_candidates.py` 明明配置了内网 backend，却直接掉到 `opencode` / `codex` / `agy`
- telemetry 里出现 `401`、`Connection error`、`invalid_json_schema`
- `daily_summary.py` / `weekly_summary.py` 变慢，因为前置 API backend 失败后才轮到 CLI

检查顺序：
1. 确认 `private/agent/data_hub.runtime.jsonc` 的 `llm.backends` 顺序是否符合预期
2. 确认 `api_key` 是单一最终值，不要在同一个 backend 对象里重复写两次 `api_key`
3. 若 `api_key` 写成 `$ENV_VAR`，检查环境变量是否真实导出；未导出时占位符字符串会原样传给 backend
4. 直接做最小探针，确认当前生效配置：

```bash
cd ~/work/config/mac-bootstrap
template/.venv/bin/python -c 'import json, sys; sys.path.insert(0, "template/agent/data-hub"); from llm_filter import load_backends, OpenAIAPIBackend, BackendRequest; cfg=load_backends()["backends"][0]; resp=OpenAIAPIBackend(cfg).generate(BackendRequest(prompt="只返回 JSON: {\"ok\": true}", timeout=15)); print(json.dumps(resp.__dict__, ensure_ascii=False))'
```

5. 若探针返回 `401`，先看 key；若返回 `Connection error`，再看内网路由、代理/TUN、sandbox 或宿主机网络
6. 若 API 已返回文本但仍 fallback，检查返回内容是不是完整 JSON schema；结构化筛选路径会把缺字段或 HTML 错页视为失败

补充说明：
- `call_llm_raw()` 只要求首个非空文本，适用于 `daily_summary.py` / `weekly_summary.py`
- `score_one()` / `filter_candidates_batch()` 要求完整 `FilterResult` schema，适用于 `generate_candidates.py`
- 因此“backend 能聊天”不等于“llm_filter 结构化筛选一定成功”；还要看输出是否符合 schema

## 15. Obsidian 插件仍指向旧路径

检查插件配置是否仍指向旧目录（`daily/`、`weekly/` 等）。

v2 目标模型里，`10_Periodic/Weekly|Monthly|Quarterly|Yearly/` 属于待删除 legacy 目录；新的自动周报/月报/季报/年报不再写这些目录，而应进入 `70_Summaries/`。

当前标准路径：

| 旧路径 | 新路径 |
|--------|--------|
| `daily/` | `10_Periodic/Daily` |
| `templates/` | `00_System/Templates` |
