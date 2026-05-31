# Agent Reboot Kit

Used when context is lost, session degraded, or starting fresh.
Provides structured state restoration.

## When to Use

- `/reboot` — Full context reset, restore from last checkpoint
- `/reboot --compact` — Compact context with strategic pruning
- `/reboot status` — Show current session health

## Files

| File | Purpose |
|------|---------|
| `restore.md` | Rebuild agent state from ~/.agent/artifacts |
| `compact.md` | Strategic compaction checklist |
| `handoff.md` | Session handoff template |
