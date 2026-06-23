# Shell Startup

This bootstrap splits shell startup into three layers. Keep their roles narrow.

## Order

1. `~/.zshenv` -> `template/shell/zshenv`
2. `~/.shell_env` -> `template/shell/shell_env`
3. `~/.zshrc` -> `template/shell/zshrc`

## Responsibilities

`zshenv` is the earliest hook. It must stay minimal: stable `PATH` setup only.
Do not put prompt logic, proxy toggles, tmux attach logic, or anything that
expects an interactive terminal here.

`shell_env` is shared by bash and zsh. It owns machine-wide environment such as
locale, proxy helpers, Conda/NVM bootstrap, and Codex sandbox path relocation
for `RTK_DB_PATH` and `CRG_DATA_DIR`.

`zshrc` is the interactive layer. It owns zinit, Powerlevel10k, aliases,
direnv, host-specific wrappers, and tmux auto-attach.

## Tmux And Daemon

`scripts/tmux-workspace.sh` starts tmux panes with `/bin/zsh -il`. This matters:

- `-l` keeps login-shell behavior consistent with a fresh terminal tab
- `-i` guarantees the pane runs the interactive startup path in `zshrc`

The `_daemon_` window uses the same rule for the `shell` and `notes` panes, and
the Codex pane falls back to `exec /bin/zsh -il` after `codex` exits.

## Prompt Caveat

Powerlevel10k instant prompt is sourced at the top of `zshrc`, but the full
theme loads later after the interactive guard. In tmux panes, `stdin`/`stdout`
TTY readiness can briefly lag during startup. Because of that, the guard in
`zshrc` must not reject interactive shells inside tmux only because `-t 0/1`
is momentarily false.

Current rule:

```zsh
if [[ ! -o interactive || ( -z "${TMUX:-}" && ( ! -t 0 || ! -t 1 ) ) ]]; then
  return 0
fi
```

That keeps GUI env-probing shells side-effect free, while allowing tmux panes to
finish the interactive startup path and load p10k.

## Debug Checklist

Use this when a pane falls back to the plain `%`/`hostname` prompt:

```bash
echo $TMUX
echo $options[interactive]
echo $(( $+functions[p10k] ))
ps -o command= -p $$
```

Expected tmux-pane state:

- `$TMUX` is non-empty
- `interactive` is `on`
- `p10k` function exists
- shell command includes `/bin/zsh -il` for tmux-managed panes
