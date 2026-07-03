# Agent Data Hub & Daily Summary 系统运维手册

本模块负责本地 AI 助手日志的定时抽取、摘要生成以及向 Obsidian 知识库的自动化回写。

## 架构概览 (Architecture)

1. **`ingest_logs.py` (日志增量抓取)**
   - 抓取本地 `~/.gemini/antigravity-cli/brain/` 下的 `transcript.jsonl` 文件。
   - 解析用户的输入和工具调用的执行情况。
   - 增量入库至 `private/agent/data/agent_history.db` (SQLite)。

2. **`daily_summary.py` (日报总结与回写)**
   - 从 `agent_history.db` 查询指定日期（默认昨日）的所有交互。
   - 根据 `agent/skills/daily-tagger/SKILL.md` 的提示词规范，调用大语言模型进行分类和总结。
   - 自动寻找 Obsidian Vault 中对应的 `YYYY-MM-DD.md` 日报文件，并执行幂等（Idempotent）更新（无缝替换 `## AI 总结` 标签后的内容）。

3. **`daily_morning.sh` (晨间初始化守护脚本)**
   - 定时执行（如每天 08:30），自动以标准模板创建当天的 `YYYY-MM-DD.md`。
   - 自动将前一日遗留的“明日计划” Task (`- [ ]`) 迁移到今天的“今日重点”中。
   - 触发 macOS 本地弹窗通知提醒。

4. **`launchd/install_obsidian_jobs.sh` (定时任务注入)**
   - 将上述 bash 和 python 脚本打包为 macOS `launchd` plist 配置。
   - 接管原本的 crontab，提供更原生的后台运行和唤醒能力。

---

## 环境变量配置 (.env)

数据中心的所有运行依赖位于 `private/agent/.obsidian_daily.env`，必须包含以下核心变量：
```bash
OBSIDIAN_VAULT_DIR="/Users/suai/work/knowledge"
DATA_HUB_DB_PATH="/Users/suai/work/config/mac-bootstrap/private/agent/data/agent_history.db"
# 以及你提供给 Python 脚本调用的大模型 API 密钥（如 OPENAI_API_KEY 或 ANTHROPIC_API_KEY）
```

---

## 日常运维与故障排查

### 1. 手动补跑 (Backfill) 某日的总结
如果由于断网或关机导致昨天的 AI 总结没有成功生成，你可以手动进入本目录执行：
```bash
# 激活环境（确保有相关 python 包如 sqlite3, openai 等）
source /Users/suai/work/config/mac-bootstrap/.venv/bin/activate
export $(grep -v '^#' ../../private/agent/.obsidian_daily.env | xargs)

# 强制重跑特定日期的日志解析与总结
python3 daily_summary.py --date 2026-07-02
```

### 2. 数据库查看
整个历史对话都离线存在于 SQLite 中。如果你想看最近解析到了哪些对话，可以使用：
```bash
sqlite3 ../../private/agent/data/agent_history.db "SELECT timestamp, user_prompt FROM conversations ORDER BY timestamp DESC LIMIT 5;"
```
如果发现某些记录没有解析进去，可以执行 `python3 ingest_logs.py --full-refresh` 强行清空并全量重刷。

### 3. 日志诊断
如果 MacOS 的定时任务没有按预期工作，通过 launchd 查看标准错误输出（在 plist 配置中定义的位置），或者直接查看脚本运行时抛出的 stdout/stderr。
如果总结发生“无限重复粘贴”，请检查 `daily_summary.py` 中的正则表达式清洗逻辑是否被意外破坏。当前设计已自带幂等保护机制。
