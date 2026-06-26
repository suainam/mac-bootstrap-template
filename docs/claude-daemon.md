# Claude Daily Drill in tmux

This document describes the tmux-first daily drill path for Claude Code.

## Recommended workflow

1. Start the AI workspace:

```bash
make tmux-workspace
```

2. If you already have a session, attach or switch to it:

```bash
tmux list-sessions
tmux attach -t ai-work
tmux switch-client -t ai-work
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
- Daemon window: `daemon`, `remote`, `work`
- Analysis window: `shell`, `python`, `sql`, `notes`
- Pane headers: `pane title | cwd | branch` with generic fallback names when unnamed

## Verification

```bash
tmux list-keys
tmux list-sessions
tmux show -gv mode-keys
```

## Notes

- `tmux` is the terminal entrypoint for this migration track.
- Daily drill is run against the tmux Claude pane.
- Hammerspoon stays at the OS tier for hotkeys, window placement, and clipboard helpers.
- Shell startup details live in [`shell-startup.md`](shell-startup.md). The
  daemon panes are expected to boot through `/bin/zsh -il`, not a partial shell
  path that skips interactive prompt loading.
