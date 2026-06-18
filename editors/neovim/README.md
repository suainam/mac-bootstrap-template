# Neovim / LazyVim

`template/editors/neovim/config/` is a repo-managed LazyVim config.

## What this setup does

- Uses `LazyVim` as the base distribution
- Keeps the main theme on `catppuccin-mocha`
- Integrates pane navigation with `tmux` via `Option-h/j/k/l`
- Uses a dedicated `uv`-managed Python host for Neovim providers:
  - `~/.local/share/neovim-python/bin/python`
- Disables unused `node` / `ruby` / `perl` providers to reduce healthcheck noise

## Install / refresh

From the repo root:

```bash
bash template/editors/neovim/install.sh
```

What it does:

- links `~/.config/nvim` to `template/editors/neovim/config`
- creates the dedicated Python host with `uv`
- installs `pynvim`
- runs `:Lazy sync`

## Clipboard best practice

This setup intentionally uses:

```lua
vim.opt.clipboard = vim.env.SSH_CONNECTION and "" or "unnamedplus"
```

Why:

- local macOS session:
  - use `unnamedplus`
  - yanks/pastes sync with the system clipboard by default
- SSH session:
  - do not force the local clipboard provider
  - let terminal / `tmux` / `OSC52` handle clipboard flow

For this repo's terminal stack, clipboard works best as a layered setup:

1. Neovim local session uses `unnamedplus`
2. `tmux` keeps `set-clipboard on`
3. `tmux` copy-mode keeps `pbcopy` bindings as a macOS fallback
4. Ghostty provides terminal support for the clipboard path

Local startup also adds a yank fallback in `TextYankPost`, so normal yanks such
as `yy` and `yG` still populate the macOS clipboard even if LazyVim temporarily
defers the built-in clipboard option during startup.

## Daily usage

Leader key: `Space`

Useful keys:

- `Space e`: explorer / file tree
- `Space f f`: find files
- `Space f g`: grep project
- `Space /`: search current buffer
- `Space ,`: recent files
- `g d`: go to definition
- `g r`: references
- `K`: hover docs
- `Space c a`: code action
- `Space c r`: rename
- `Space g g`: open `lazygit`
- `Option-h/j/k/l`: move between Neovim splits and `tmux` panes

## Health checks

Useful commands:

```vim
:checkhealth
:checkhealth vim.provider
:checkhealth lazy
:checkhealth conform
:checkhealth grug-far
```

Expected state:

- local use should prefer `unnamedplus`
- remote SSH use may leave clipboard routing to `OSC52`
- `mason`, `which-key`, and some image-related checks may still show informational warnings if optional runtimes are not installed

## Files

- `config/init.lua`: startup globals that must be set before plugin load
- `config/lua/config/options.lua`: Neovim options
- `config/lua/config/keymaps.lua`: small local keymap overrides
- `config/lua/plugins/core.lua`: core LazyVim overrides
- `config/lua/plugins/tooling.lua`: tooling/healthcheck noise reduction overrides
- `config/lazyvim.json`: LazyVim metadata file
