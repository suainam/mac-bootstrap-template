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

## AI support

This setup includes `CodeCompanion.nvim` with an `openai_compatible` adapter.

Default behavior:

- adapter name: `openai_compat`
- provider type: `OpenAI-compatible`
- no fallback to OpenAI official API
- runtime config should come from private repo config

For this repo, a more robust private override is supported via:

`private/editors/neovim/ai.lua`

Example:

```lua
return {
  ["api" .. "_key"] = "...",
  base_url = "https://example.com/v1",
  model = "mimo-v2.5-pro",
}
```

This avoids relying on shell startup env when Neovim is launched from GUI tools or tmux restore flows.

Useful keys:

- `Space a a`: action palette
- `Space a c`: toggle AI chat
- visual `Space a s`: send selection to chat
- insert `Ctrl-y`: accept current AI prediction reliably across terminals
- insert `Option-y`: accept current AI prediction
- insert `Option-l`: accept one line from current AI prediction
- insert `Option-]`: next AI prediction / trigger manually
- insert `Option-[`: previous AI prediction
- insert `Option-e`: dismiss current AI prediction

Useful commands:

```vim
:CodeCompanionActions
:CodeCompanionChat Toggle
:CodeCompanion explain this function
:Minuet virtualtext toggle
```

For automatic prediction, this setup also includes `minuet-ai.nvim`.

Behavior:

- insert mode auto-triggers AI prediction on most code filetypes
- `markdown`, `text`, `help`, `gitcommit`, `neo-tree`, `oil`, and `TelescopePrompt` are excluded
- prediction uses the same private `ai.lua` runtime config as chat/edit
- chat/edit stays on `CodeCompanion.nvim`; auto prediction stays on `Minuet`

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
- `config/lua/plugins/ai.lua`: AI assistant via `CodeCompanion.nvim`
- `config/lua/plugins/ai-completion.lua`: automatic AI prediction via `minuet-ai.nvim`
- `config/lua/plugins/core.lua`: core LazyVim overrides
- `config/lua/plugins/tooling.lua`: tooling/healthcheck noise reduction overrides
- `config/lazyvim.json`: LazyVim metadata file
