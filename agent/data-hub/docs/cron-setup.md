# Cron Setup for Agent Data Hub

This document explains how to configure automated pipeline execution using Codex CronCreate.

## Health Check

The health check script monitors pipeline execution and reports failures from the last 3 days.

### Codex CronCreate Configuration

```bash
# In Codex, run:
/cron create "0 10 18 * * *" "python $HOME/work/config/mac-bootstrap/template/agent/data-hub/scripts/health_check.py"
```

**Schedule**: Every day at 18:10 (6:10 PM)
**Command**: `python $HOME/work/config/mac-bootstrap/template/agent/data-hub/scripts/health_check.py`

### Optional macOS Notifications

To enable notifications when failures are detected:

```bash
export ENABLE_NOTIFICATIONS=true
```

Add this to `private/agent/data_hub.runtime.jsonc`.

## Full Pipeline Automation

You can also automate the full archive/render pipeline:

### Evening Full Cycle (18:00)

```bash
/cron create "0 0 18 * * 1-5" "cd $HOME/work/config/mac-bootstrap && template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py run --workflow full_cycle --date $(date +%F)"
```

**Schedule**: Every weekday at 18:00
**Purpose**: Run archive_to_sqlite then render_obsidian through the durable manager.

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
python template/agent/data-hub/scripts/health_check.py

# Full pipeline for a specific date
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow full_cycle --date 2026-07-04
```
