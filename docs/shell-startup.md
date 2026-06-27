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
for `RTK_DB_PATH`.

`zshrc` is the interactive layer. It owns zinit, Powerlevel10k, aliases,
direnv, host-specific wrappers, and tmux auto-attach.

## Tmux And Daemon

`scripts/tmux-workspace.sh` starts tmux panes with `/bin/zsh -il`. This matters:

- `-l` keeps login-shell behavior consistent with a fresh terminal tab
- `-i` guarantees the pane runs the interactive startup path in `zshrc`

The `_daemon_` window uses the same rule for the `remote` and `work` panes, and
the Codex pane falls back to `exec /bin/zsh -il` after `codex` exits.

## Prompt Caveat

Powerlevel10k instant prompt is sourced at the top of `zshrc`, but the full
theme loads later after the interactive guard. The guard must not block p10k
for any real terminal — tmux panes, Apple_Terminal, iTerm2, Ghostty, etc.

The guard only needs to block headless env-probing shells (Zed, VSCode, GUI
editors that capture the login environment without a real terminal). Those
shells lack `stdin` (`-t 0` is false); checking stdin alone is sufficient.

Current rule:

```zsh
if [[ ! -o interactive || ( -z "${TMUX:-}" && ! -t 0 ) ]]; then
  return 0
fi
```

Why `! -t 0` only (not `! -t 0 || ! -t 1`): Apple_Terminal opens new windows
with `stdout` not bound to a TTY (`-t 1` is false), so the old two-sided check
incorrectly triggered the early return and blocked p10k from loading.

`POWERLEVEL9K_INSTANT_PROMPT` must be set to `quiet` (not `verbose`) in
`p10k.zsh`. The `verbose` setting fires a warning whenever any console output
appears during zsh initialization; `quiet` suppresses the warning while still
loading instant prompt.

## Debug Checklist

Use this when a shell falls back to the plain `%`/`hostname` prompt:

```bash
echo $TMUX
echo $options[interactive]
[[ -t 0 ]] && echo "stdin=tty" || echo "stdin=no-tty"
[[ -t 1 ]] && echo "stdout=tty" || echo "stdout=no-tty"
echo $(( $+functions[p10k] ))
ps -o command= -p $$
```

Expected state for any interactive terminal (tmux or native):

- `interactive` is `on`
- `stdin=tty` (`-t 0` must be true for the guard to pass)
- `p10k` function exists

Known limitation: if two terminal windows start simultaneously (e.g., opening
two Apple_Terminal windows at once), the second window may show a plain prompt
until the first window's gitstatus daemon finishes initializing. This is a
gitstatus multi-instance race condition; opening windows a second apart avoids
it.
