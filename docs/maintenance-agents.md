# Maintenance LaunchAgents

Four user LaunchAgents run scheduled one-shot tasks:

- Claude keepalive: 00:00, 08:00, and 15:00.
- Cache cleanup: Sundays at 04:15.
- Downloads organizer: every 30 minutes.
- System patrol: daily at 21:00 (trash emptying, package/bun/npm/Docker cache hygiene, runaway log auto-rotation, crash & resource alarms, notification on fault).

Install or refresh all four from the template checkout:

```bash
make install-maintenance-agents
```

Install or unload one task from the template checkout:

```bash
./scripts/install-maintenance-agents.sh install cache-cleanup
./scripts/install-maintenance-agents.sh unload cache-cleanup
```

Legacy `make install-cache-agent`, `make install-downloads-agent`, and `make claude-daemon-install` targets use the same placeholder renderer and reload logic.
