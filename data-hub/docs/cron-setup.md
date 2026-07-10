# Data Hub Schedule

现行 macOS 自动化由 `template/launchd/install_obsidian_jobs.sh` 安装：

| 时间 | 任务 | 日历规则 |
|---|---|---|
| 09:00 | `daily_morning.sh` 创建日报并迁移计划 | `chinese_calendar` 工作日，含调休 |
| 17:30 | `daily_reminder.sh` 提醒补充工作记录 | `chinese_calendar` 工作日，含调休 |
| 18:00 | `run-daily-evening.sh` 调度 Summary Engine | 每个自然日 |

安装或刷新：

```bash
cd ~/work/config/mac-bootstrap
bash template/launchd/install_obsidian_jobs.sh
```

晚间任务通过 lifecycle manager 运行 `build_daily_summary`，并按周期边界依次补齐 Weekly、Monthly、Quarterly、Yearly；产物进入 `70_Summaries/Daily` 及对应上层目录。

## 可选 Codex Cron Fallback

只有不使用 launchd 时，才为 18:00 晚间调度创建以下 fallback；不要与 launchd 重复安装：

```bash
/cron create "0 0 18 * * *" "cd $HOME/work/config/mac-bootstrap && bash template/data-hub/run-daily-evening.sh"
```

**Schedule**: Every day at 18:00

查看或删除：

```bash
/cron list
/cron delete <job-id>
```

旧 Codex Cron 健康检查方案见 [archive/cron-setup-legacy.md](./archive/cron-setup-legacy.md)，仅作历史参考。日常运行和补跑以 [ops.md](./ops.md) 为准。
