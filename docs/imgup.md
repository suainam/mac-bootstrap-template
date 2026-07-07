# imgup — CloudFlare-ImgBed CLI Uploader

## Overview

`imgup` uploads images to a CloudFlare-ImgBed instance and copies the public URL
to your clipboard. Designed for quick paste-and-use workflows in Obsidian, nvim,
and terminal.

## Architecture

```
┌─────────────┐    ┌─────────────┐    ┌──────────────────┐
│  imgup CLI  │───▶│  curl POST  │───▶│ CloudFlare-ImgBed│
│  ~/.local/  │    │  Bearer     │    │  (Telegram      │
│  bin/imgup  │    │  auth       │    │   storage)      │
└─────────────┘    └─────────────┘    └──────────────────┘
       │
       ├── reads: private/imgbed/config.jsonc (upload_api_key)
       └── outputs: URL → stdout + clipboard (pbcopy)
```

## Setup

### Prerequisites

- `private/imgbed/config.jsonc` exists with a valid `upload_api_key`
- `python3` available (for JSON parsing)
- `curl` installed

### Install

```bash
# Via Makefile (automatic during bootstrap):
make imgup-install

# Or direct:
./template/scripts/install-imgup.sh

# Verify:
imgup --help
```

The installer creates `~/.local/bin/imgup → template/scripts/imgup.sh` and
validates that the private config file is present and readable.

### Configuration

File: `private/imgbed/config.jsonc` (never committed to public template)

```jsonc
{
  "upload_api_key": "imgbed_sAdHLcgqkzHCNZFipgtxVr743Jc9Zn0m"
}
```

The upload API key is generated in the ImgBed admin panel:
`Admin Panel → System Settings → Security Settings → API Token Management`.

## Usage

### Upload from clipboard (推荐)

截图或复制图片后直接上传，无需先存文件：

```bash
imgup -p -m
# Reads clipboard image, uploads, copies Markdown link to clipboard
# Paste into Obsidian/nvim: cmd+V
```

`-p` 读取剪贴板图片，需要 `pngpaste`（`make bootstrap` 自动安装）。

### Basic upload

```bash
imgup screenshot.png
# Output: https://img.saui.dpdns.org/file/1712345678_screenshot.png
# Also copies URL to clipboard
```

### Markdown format

```bash
imgup -m screenshot.png
# Output: ![](https://img.saui.dpdns.org/file/1712345678_screenshot.png)
```

### Batch upload

```bash
imgup photo1.jpg photo2.jpg photo3.png
# Output: three URLs, last one copied to clipboard
```

### Quiet mode (no clipboard)

```bash
imgup -q screenshot.png
# Output: URL to stdout only, clipboard unchanged
```

## Integration Guides

### Obsidian (推荐: 截图→上传→粘贴 3秒流程)

**核心流程：** 截图 → `imgup -p -m` → 粘贴

```
                cmd+shift+4         cmd+V
  ┌──────────┐  ────────▶  ┌────┐ ──────▶  ┌──────────┐
  │ 截图     │             │imgup│          │ Obsidian │
  │→剪贴板   │──────────▶  │ -p  │─────────▶│ 粘贴     │
  │          │  终端执行   │ -m  │ Markdown │ ![](url) │
  └──────────┘             └────┘          └──────────┘
                              │ 自动 pbcopy
```

一步到位：截图 → 切到终端 `imgup -p -m` → 切回 Obsidian `Cmd+V`

**Option A: 纯键盘流 (no plugin)**

适合 Obsidian Vim 模式的用户：

1. 截图 (Cmd+Shift+4) → 图片在剪贴板
2. 切换到终端, 运行 `imgup -p -m`
3. 切回 Obsidian, `Cmd+V` 粘贴 `![](url)`

也可以绑定到全局快捷键（macOS 系统设置 → 键盘 → 快捷键 → 服务）：

| 服务名称 | 执行脚本 | 快捷键建议 |
|---------|---------|-----------|
| Upload to ImgBed | `~/.local/bin/imgup -p -m` | Cmd+Shift+U |

绑定后：截图 → 按快捷键 → 粘贴到 Obsidian，无需离开编辑器。

**Option B: obsidian-image-auto-upload-plugin**

1. Install `obsidian-image-auto-upload-plugin` from Community Plugins
2. In plugin settings, set custom uploader command to: `imgup -q`
3. Paste image from clipboard → plugin auto-saves, calls imgup, inserts URL

### Neovim / Vim

**Upload current file:**
```vim
:!imgup %
```

**Upload selected file (visual mode):**
```vim
:'<,'>!imgup 
```

**With image.nvim or similar:**
Configure paste handler to pipe through imgup.

**As a keymapping:**
```lua
-- Paste and upload
vim.keymap.set('n', '<leader>iu', ':!imgup %<CR>', { desc = 'Upload current file to ImgBed' })
```

### PicGo (GUI)

CloudFlare-ImgBed supports PicGo's custom uploader format:

1. Install PicGo: `brew install picgo`
2. Install `picgo-plugin-custom-uploader`
3. Configure:
   - POST URL: `https://img.saui.dpdns.org/upload?returnFormat=full`
   - Custom Header: `{"Authorization": "Bearer YOUR_API_KEY"}`
   - JSON Path: `src`
4. PicGo can then be used by Obsidian plugins that support PicGo

### Shell script for scripts

```bash
#!/bin/bash
# Upload and get Markdown link
url=$(imgup -q "$1" 2>/dev/null)
echo "![]($url)" | pbcopy
```

## File Locations

| Path | Purpose |
|------|---------|
| `template/scripts/imgup.sh` | Uploader script (public) |
| `template/scripts/install-imgup.sh` | Distribution/install script (public) |
| `private/imgbed/config.jsonc` | API key + credentials (private, git-encrypted) |
| `~/.local/bin/imgup` | Symlink to imgup.sh (created by installer) |

## Troubleshooting

**"Cannot find private/imgbed/config.jsonc"**
→ Create `private/imgbed/config.jsonc` with `{ "upload_api_key": "your-token" }`
→ Or set `MAC_BOOTSTRAP_PRIVATE_DIR=/path/to/private`

**"upload_api_key is empty"**
→ The config file exists but the key field is missing or blank
→ Check spelling: the field is `upload_api_key`

**"HTTP 401 Unauthorized"**
→ The API key is invalid or expired
→ Regenerate in admin panel → System Settings → Security Settings → API Token Management

**"Upload failed: (empty response)"**
→ Network issue or the ImgBed instance is down
→ Check `curl -sS https://img.saui.dpdns.org/adminLogin` returns 200

## Makefile Targets

```bash
make imgup          # Install/update imgup symlink (alias for imgup-install)
make imgup-install  # Install/update imgup + validate config
make bootstrap      # Full bootstrap (includes imgup via install.sh)
```
