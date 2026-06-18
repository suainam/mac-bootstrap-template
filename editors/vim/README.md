# Vim

`template/editors/vim/vimrc` is the repo-managed config for terminal Vim.

## Install / refresh

From the repo root:

```bash
bash template/editors/vim/install.sh
```

What it does:

- links `~/.vimrc` to `template/editors/vim/vimrc`
- links `~/.vim/theme.vim` to the default theme
- installs `vim-plug` if needed
- runs `PlugUpdate` / `PlugInstall`

## Clipboard behavior

Terminal Vim keeps local yanks synced to the macOS clipboard:

- `set clipboard=unnamedplus` is the default
- `VimEnter` restores `unnamedplus` if startup leaves `clipboard` empty
- `TextYankPost` mirrors normal yanks such as `yy` and `yG` into the `+`
  register, so they stay pasteable in other macOS apps

This keeps legacy Vim aligned with the Neovim setup for local terminal use.

## Files

- `vimrc`: main Vim config
- `themes/`: tracked color schemes
- `switch-theme.sh`: theme switch helper
