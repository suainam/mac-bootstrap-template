# Claude Daily Drill in Zellij

This document describes the Zellij-first daily drill path for Claude Code.

## Recommended workflow

1. Start the AI workspace:

```bash
make zellij-workspace
```

2. If you already have a session, attach or switch to it:

```bash
zellij list-sessions
zellij attach -c ai-work
zellij action switch-session ai-work
```

3. Use the native daily drill launcher:

```bash
make claude-daily-drill-run
```

4. Export the latest drill result:

```bash
make claude-daily-drill-export
```

## Session layout

- Default session: `ai-work`
- Default layout: `ai-work`
- Claude pane: the pane running `claude`
- Side panes: `SSH` and `Zsh`

## Verification

```bash
zj list-keys
zellij list-sessions
zellij setup --check
```

## Notes

- `zj` is the terminal entrypoint for this migration track.
- Daily drill is run against the Zellij Claude pane.
- Hammerspoon stays at the OS tier for hotkeys, window placement, and clipboard helpers.
