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
      ├─ 8-19 / 23:30-00:30 only
      ├─ Checks ~/.claude/projects/ for latest .jsonl mtime
      ├─ Idle >= 230s → sends # cache_check to tmux pane
      └─ Idle < 230s → silent exit
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

## Logs

```bash
# Tmux daemon
tail -f ~/Library/Logs/claude-daemon/tmux.log

# Keepalive
tail -f ~/Library/Logs/claude-daemon/keepalive.log

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

# Stop
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/io.local.mac-bootstrap.claude-daemon.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/io.local.mac-bootstrap.claude-keepalive.plist

# Via Makefile:
make claude-daemon-status
make claude-daemon-unload

# Granular keepalive control:
make claude-keepalive-enable
make claude-keepalive-disable
make claude-keepalive-status
```

## Health check

```bash
grep HEALTH_CHECK ~/Library/Logs/claude-daemon/tmux.log
grep "SENT" ~/Library/Logs/claude-daemon/keepalive.log
```
