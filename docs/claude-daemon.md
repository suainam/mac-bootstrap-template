# Claude Code Daemon (macOS)

Keeps a Claude Code session alive inside tmux by periodically injecting
cache-check comments before the 300s cache TTL expires.

## Architecture

```
launchd: io.local.mac-bootstrap.claude-daemon (KeepAlive)
  └─ scripts/claude-daemon-tmux.sh
      ├─ Starts tmux server + _daemon_ session
      ├─ Launches claude in a retry loop
      └─ Health check every 10 minutes

launchd: io.local.mac-bootstrap.claude-keepalive (every 60s)
  └─ scripts/claude-daemon-keepalive.sh
      ├─ Weekdays, work windows only
      ├─ Checks ~/.claude/projects/ for latest .jsonl mtime
      ├─ Idle >= 230s and recent activity → sends # cache_check
      └─ Long inactivity or off-hours → silent exit

launchd: io.local.mac-bootstrap.claude-daily-drill (every 15m + boot catch-up)
  └─ scripts/claude-daily-drill.sh
      ├─ Runs at/after 09:35, once per calendar day
      ├─ Reuses the daemon tmux pane
      ├─ Retries after reboot until Claude is ready
      ├─ Explicitly invokes daily-claude-battle-boost
      ├─ Generates one daily practice card
      └─ Spawns an exporter that writes markdown to ~/work/logs/claude-daily-drill/
```

Safety margin: `threshold(230) + timer(60) = 290 < TTL(300) = 10s`

## Install

```bash
# Bootstrap copies plists to ~/Library/LaunchAgents/ with {{BOOTSTRAP}} resolved
make install
make render-configs

# Load services
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.local.mac-bootstrap.claude-daemon.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.local.mac-bootstrap.claude-keepalive.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.local.mac-bootstrap.claude-daily-drill.plist

# Or use Makefile targets (if configured):
make claude-daemon-install
```

## Configuration

Set these environment variables in `~/.zshrc.local` or private overlay:

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_PROJECT_DIR` | `$HOME/work` | Project directory for claude |
| `CLAUDE_SESSION` | `_daemon_` | tmux session name |
| `CLAUDE_PANE_TITLE` | `claude-keepalive` | tmux pane title |
| `CLAUDE_THRESHOLD` | `230` | Idle seconds before cache_check |
| `CLAUDE_WORK_WINDOWS` | `09:00-12:30,13:30-18:30` | Weekday office windows for keepalive |
| `CLAUDE_ACTIVE_MAX_IDLE` | `5400` | Stop keepalive after this much inactivity |

## Logs

```bash
# Tmux daemon
tail -f ~/Library/Logs/claude-daemon/tmux.log

# Keepalive
tail -f ~/Library/Logs/claude-daemon/keepalive.log

# Daily drill
tail -f ~/Library/Logs/claude-daemon/daily-drill.log

# Exporter
tail -f ~/Library/Logs/claude-daemon/daily-drill-export.log

# launchd stdout/stderr (also in unified log)
cat /tmp/claude-daemon-tmux.log
cat /tmp/claude-daemon-keepalive.log

# Via Makefile:
make claude-daemon-logs
```

## Management

```bash
# Status
launchctl print gui/$(id -u)/io.local.mac-bootstrap.claude-daemon
launchctl print gui/$(id -u)/io.local.mac-bootstrap.claude-keepalive
launchctl print gui/$(id -u)/io.local.mac-bootstrap.claude-daily-drill

# Stop
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/io.local.mac-bootstrap.claude-daemon.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/io.local.mac-bootstrap.claude-keepalive.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/io.local.mac-bootstrap.claude-daily-drill.plist

# Via Makefile:
make claude-daemon-status
make claude-daemon-unload

# Granular keepalive control:
make claude-keepalive-enable
make claude-keepalive-disable
make claude-keepalive-status
make claude-daily-drill-enable
make claude-daily-drill-disable
make claude-daily-drill-status
make claude-daily-drill-run
make claude-daily-drill-export
```

## Health check

```bash
grep HEALTH_CHECK ~/Library/Logs/claude-daemon/tmux.log
grep "SENT" ~/Library/Logs/claude-daemon/keepalive.log
grep "SENT daily drill" ~/Library/Logs/claude-daemon/daily-drill.log
```
