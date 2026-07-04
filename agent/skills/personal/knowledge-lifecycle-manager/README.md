# Knowledge Lifecycle Manager

Unified command center for the data-hub knowledge pipeline.

## Purpose

Single entry point for all knowledge pipeline operations:
- Run daily workflow (ingest → auto_review → materialize → summary)
- Check execution status and health
- Inspect candidate queues
- Rerun specific dates or stages

## Usage

### Unified Entry

```bash
# Run today's full pipeline
./run.sh

# Rerun specific date
./run.sh run --workflow full_cycle --date 2026-07-01

# Named workflows
./run.sh run --workflow daily_ingest_and_review --date 2026-07-01
./run.sh run --workflow daily_promote_and_summary --date 2026-07-01
./run.sh run --workflow weekly_hygiene_and_reuse --date 2026-07-01

# Legacy aliases
./run.sh --ingest-only
./run.sh --review-only
./run.sh --materialize-only
```

### Status & Monitoring

```bash
# Show today's execution status
./run.sh status
./run.sh status --date 2026-07-01

# Show candidate queue
./run.sh candidates
./run.sh candidates 2026-07-01

# Health check (last 3 days)
./run.sh health
```

## Architecture

- `SKILL.md` — Skill metadata for Claude Code
- `run.sh` — Shell wrapper for direct invocation
- `scripts/manager.py` — Public control plane for run/status/candidates/health
- `template/agent/data-hub/knowledge_workflows.py` — Canonical workflow registry
- `template/agent/data-hub/run-daily-evening.sh` — Thin adapter that delegates to manager

## Integration

Registered in `template/agent/skills-distribution.json` as project-scoped skill.
Symlinked to `~/.claude/skills/knowledge-lifecycle-manager` by bootstrap.
