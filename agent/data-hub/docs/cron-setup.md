# Cron Setup for Agent Data Hub

This document explains how to configure automated pipeline execution using Codex CronCreate.

## Health Check

The health check script monitors pipeline execution and reports failures from the last 3 days.

### Codex CronCreate Configuration

```bash
# In Codex, run:
/cron create "0 10 18 * * *" "python $HOME/work/config/mac-bootstrap/template/agent/data-hub/health_check.py"
```

**Schedule**: Every day at 18:10 (6:10 PM)
**Command**: `python $HOME/work/config/mac-bootstrap/template/agent/data-hub/health_check.py`

### Optional macOS Notifications

To enable notifications when failures are detected:

```bash
export ENABLE_NOTIFICATIONS=true
```

Add this to `private/agent/data_hub.runtime.jsonc`.

## Full Pipeline Automation

You can also automate the full data ingestion and summary pipeline:

### Evening Data Collection (18:00)

```bash
/cron create "0 0 18 * * 1-5" "cd $HOME/work/config/mac-bootstrap && template/.venv/bin/python template/agent/data-hub/ingest_logs.py && template/.venv/bin/python template/agent/data-hub/ingest_sources.py"
```

**Schedule**: Every weekday at 18:00
**Purpose**: Collect agent logs and external sources before generating summary

### Daily Summary (19:00)

```bash
/cron create "0 0 19 * * 1-5" "cd $HOME/work/config/mac-bootstrap && template/.venv/bin/python template/agent/data-hub/daily_summary.py"
```

**Schedule**: Every weekday at 19:00
**Purpose**: Generate AI summary for daily note

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
python template/agent/data-hub/health_check.py

# Full pipeline for a specific date
python template/agent/data-hub/ingest_logs.py
python template/agent/data-hub/ingest_sources.py
python template/agent/data-hub/generate_candidates.py 2026-07-04
python template/agent/data-hub/daily_summary.py 2026-07-04
```
