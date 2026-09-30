# Maintenance LaunchAgents

Three user LaunchAgents run scheduled one-shot tasks:

- Claude keepalive: 00:00, 08:00, and 15:00.
- Cache cleanup: Sundays at 04:15.
- Downloads organizer: every 30 minutes.

Install or refresh all three from the template checkout:

```bash
make install-maintenance-agents
```

Install or unload one task from the template checkout:

```bash
./scripts/install-maintenance-agents.sh install cache-cleanup
./scripts/install-maintenance-agents.sh unload cache-cleanup
```

Legacy `make install-cache-agent`, `make install-downloads-agent`, and `make claude-daemon-install` targets use the same placeholder renderer and reload logic.
