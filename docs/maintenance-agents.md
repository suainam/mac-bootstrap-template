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

The installer renders and validates each plist, backs up any previous plist,
boots out the prior job, atomically replaces the installed plist, enables it,
and bootstraps it in the current user's `gui` launchd domain. If activation
fails, it restores a previous plist and attempts to bootstrap it. On a failed
first install, it removes the new plist and attempts to disable the label. The
single-agent Make targets use the same installer.
