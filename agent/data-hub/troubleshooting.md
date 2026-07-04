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
1. `daily_summary.py` 的 `inject_summary_to_daily()`
2. 日报模板中 `## AI 总结` 是否被手工改坏

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

## 6. Obsidian 打开日报/模板失败

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
