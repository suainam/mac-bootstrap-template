# Knowledge Lifecycle Manager

Unified command center for the data-hub knowledge pipeline.

## Purpose

Single entry point for all knowledge pipeline operations:
- Delegate live agent knowledge recording to `knowledge-record`
- Run archive/render/period-summary workflows (`archive_to_sqlite`, `render_obsidian`, `full_cycle`, `build_*_summary`)
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
./run.sh run --workflow archive_to_sqlite --date 2026-07-01
./run.sh run --workflow render_obsidian --date 2026-07-01
./run.sh run --workflow full_cycle --date 2026-07-01
./run.sh run --workflow build_weekly_summary --date 2026-07-10
./run.sh run --workflow build_monthly_summary --date 2026-07-31
./run.sh run --workflow build_quarterly_summary --date 2026-09-30
./run.sh run --workflow build_yearly_summary --date 2026-12-31

# Delegate record requests to the dedicated writer skill
./run.sh record --type adr --title "..." --content "..." --date 2026-07-01

# Agent-driven suggest-first recording
./run.sh record --suggest \
  --thread-summary "本次会话完成了..." \
  --action accept \
  --agent codex
```

For `record --suggest`, lifecycle remains the control-plane entry and delegates
the record contract to `knowledge-record`. The calling agent should summarize
the active conversation itself and pass `--thread-summary`; humans should not
need to manually construct transcript JSON.

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
- `scripts/manager.py` — Public control plane for run/status/candidates/health/record delegation
- `../knowledge-record/` — Dedicated record skill package and push-path writer
- `template/agent/data-hub/knowledge_workflows.py` — Canonical workflow registry
- `template/agent/data-hub/run-daily-evening.sh` — Thin adapter that delegates to manager

## Integration

Registered in `template/agent/skills-distribution.json` as project-scoped skill.
Symlinked to `~/.claude/skills/knowledge-lifecycle-manager` by bootstrap.
