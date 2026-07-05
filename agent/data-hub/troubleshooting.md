# Data Hub 故障排查

## 1. 日报没生成

检查顺序：
1. `OBSIDIAN_VAULT_DIR` 是否正确
2. `OBSIDIAN_DAILY_DIR` 是否正确
3. Obsidian periodic-notes 目录是否已迁到 `10_Periodic/Daily`
4. `daily_morning.sh` 是否被 launchd 正常调起

## 2. 摘要写回位置不对

检查顺序：
1. `.obsidian_daily.env` 中 `OBSIDIAN_DAILY_DIR`
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

检查插件配置是否仍指向旧目录（`daily/`、`weekly/` 等）。当前标准路径：

| 旧路径 | 新路径 |
|--------|--------|
| `daily/` | `10_Periodic/Daily` |
| `weekly/` | `10_Periodic/Weekly` |
| `monthly/` | `10_Periodic/Monthly` |
| `quarterly/` | `10_Periodic/Quarterly` |
| `yearly/` | `10_Periodic/Yearly` |
| `templates/` | `00_System/Templates` |
| `wiki/` | `40_Knowledge/Wiki` |
