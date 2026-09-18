# Claude Daemon (launchd Keepalive)

This document describes the launchd-managed keepalive daemon for Claude Code.
It does not use tmux — the daemon is a plain `bash` script fired on a
calendar schedule, with no terminal multiplexer involved.

## What it does

`launchd/io.local.mac-bootstrap.claude-daemon.plist` runs
`scripts/claude-daemon.sh` at `00:00`, `08:00`, and `15:00`. Each run sends a
single non-interactive `claude -p ... --bare --no-session-persistence` ping
and exits — there is no persistent process or session between runs.

## Install / manage

```bash
make claude-daemon-install   # install + bootstrap the LaunchAgent
make claude-daemon-status    # show launchd status
make claude-daemon-logs      # tail structured run summaries
make claude-daemon-unload    # stop and remove the LaunchAgent
```

## Logs

- Structured run summaries: `~/Library/Logs/claude-daemon/daemon.log`
- Raw `claude -p` stdout/stderr (latest run only): `/tmp/claude-daemon.log`
  and `/tmp/claude-daemon.err`
- For multi-day history, use `~/Library/Logs/claude-daemon/daemon.log`
- For a one-off multi-line drill prompt, create
  `~/.claude/claude-daemon-prompt.txt`; the daemon prefers that file over the
  default keepalive prompt. Remove it after the drill so scheduled runs
  return to the default keepalive behavior.

## Anti-sleep assertion

launchd can fire this script inside a macOS maintenance DarkWake window. The
script wraps the `claude -p` child in `caffeinate -i -w <pid>` so the system
can't fall back asleep mid-run and freeze the process for minutes; the
assertion is released automatically once `claude -p` exits.

## Notes

- `tmux` is unrelated to this daemon. If you're looking for the interactive
  tmux workspace, see `make tmux-workspace` — that's a separate, unrelated
  feature for day-to-day terminal sessions.
