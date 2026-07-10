# Cron Setup for Agent Data Hub

> Historical context only. This Codex Cron setup is superseded by `template/launchd/install_obsidian_jobs.sh`, which owns the current 09:00 / 17:30 / 18:00 schedule. Do not use this file as the active installation guide.

This document explains how to configure automated pipeline execution using Codex CronCreate.

## Health Check

The health check script monitors pipeline execution and reports failures from the last 3 days.

### Codex CronCreate Configuration

```bash
# In Codex, run:
/cron create "0 10 18 * * *" "python $HOME/work/config/mac-bootstrap/template/data-hub/scripts/health_check.py"
```

**Schedule**: Every day at 18:10 (6:10 PM)
**Command**: `python $HOME/work/config/mac-bootstrap/template/data-hub/scripts/health_check.py`

### Optional macOS Notifications

To enable notifications when failures are detected:

```bash
export ENABLE_NOTIFICATIONS=true
```

Add this to `private/agent/data_hub.runtime.jsonc`.

## Summary Automation

You can also automate the summary schedule:

### Evening Summary Schedule (18:00)

```bash
/cron create "0 0 18 * * *" "cd $HOME/work/config/mac-bootstrap && bash template/data-hub/run-daily-evening.sh"
```

**Schedule**: Every day at 18:00
**Purpose**: Run build_daily_summary and any period summary triggered for the date through the lifecycle manager.

## Viewing Cron Jobs

```bash
/cron list
```

## Removing Cron Jobs

```bash
/cron delete <job-id>
```

## Manual Execution

All scripts can be run manually:

```bash
# Health check
python template/data-hub/scripts/health_check.py

# Daily summary for a specific date
template/.venv/bin/python template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow build_daily_summary --date 2026-07-04
```
