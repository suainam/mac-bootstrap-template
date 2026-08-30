# Inter-Panel Communication Buses Reference

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          3-Panel Communication Bus                          │
│                                                                             │
│               ① Human prompts agent (<leader>aa)                           │
│         ┌──────────────────────────────────────────────┐                    │
│         │                                              │                    │
│         ▼                                              │                    │
│  ┌──────────────┐     ④ Silent Toast Notice       ┌─────────────┐            │
│  │    agent     │ ─────────────────────────────►  │    nvim     │            │
│  │  (OMP/Claude)│ ◄────────────────────────────── │ (Sovereign) │            │
│  └──────┬───────┘   (Disk edit -> gitsigns/autoread)────────────┘            │
│         │                                                                   │
│         │ ② Run test / read error logs (`herdr pane read/run`)              │
│         │ ③ Direct CDP ARIA / Action                                       │
│         ▼                                                                   │
│  ┌──────────────┐                                                           │
│  │  qa-runtime  │                                                           │
│  │ (Dev/Tester) │                                                           │
│  └──────────────┘                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Bus 1: `nvim` -> `agent` (Human Task & Annotation Delegation)

### Option A: `ChmaraX/herdr-nvim` Code Annotations (Recommended)
Configured in `~/.config/nvim/lua/plugins/tooling.lua`:
```lua
{
  "ChmaraX/herdr-nvim",
  opts = {
    prefix = "<leader>h", -- Avoid collision with LazyVim native <leader>a
    clear_after_send = true,
  },
}
```
- `<leader>hc`: Comment on current line or visual selection
- `<leader>hl`: List all pending comments in a floating window
- `<leader>hS`: Send all comments (with file, line, and git context) directly to the adjacent Agent pane

### Option B: Direct Visual Selection Dispatch (`<leader>aa`)
In `~/.config/nvim/init.lua` or sourced from `scripts/herdr.lua`:
```lua
vim.keymap.set('v', '<leader>aa', function()
  local s_start = vim.fn.getpos("'<")[2]
  local s_end = vim.fn.getpos("'>")[2]
  local file = vim.fn.expand("%:p")
  
  vim.ui.input({ prompt = "Delegate task to Agent: " }, function(task)
    if not task or task == "" then return end
    local prompt = string.format("Target: %s (lines %d-%d)\nInstruction: %s", file, s_start, s_end, task)
    vim.fn.system(string.format("herdr agent prompt agent %q --no-wait", prompt))
    vim.notify("Task dispatched to agent pane", vim.log.levels.INFO)
  end)
end, { desc = "Dispatch Selection to Herdr Agent" })
```

### Herdr Host Shortcuts
- `Ctrl+a e`: Toggle persistent full-height Neovim sidebar (`chmarax.herdr-nvim.toggle`)
- `Ctrl+a o`: Open fuzzy picker of files recently touched by the Agent (`chmarax.herdr-nvim.pick-file`)
## Bus 2: `agent` -> `qa-runtime` (Test Control & Log Scraping)

```bash
# 1. Read dev server error logs
herdr pane read qa-runtime --source recent-unwrapped --lines 40

# 2. Trigger test suite in runtime pane
herdr pane run qa-runtime "npm test"
herdr pane wait-output qa-runtime --match "PASS" --timeout 15000
```

## Bus 3: `agent` <-> `Playwriter` (Deterministic Browser Testing)

```python
import subprocess
import re
import json
from contextlib import contextmanager

@contextmanager
def playwriter_session(browser: str = "headless"):
    """With-bound browser context: auto-deletes session on exit/error."""
    out = subprocess.check_output(["playwriter", "session", "new", "--browser", browser], text=True)
    match = re.search(r"Session (\d+)", out)
    if not match:
        raise RuntimeError(f"Session creation failed: {out}")
    session_id = match.group(1)
    try:
        yield session_id
    finally:
        subprocess.run(["playwriter", "session", "delete", session_id], check=False, stdout=subprocess.DEVNULL)
```

## Bus 4: `agent` -> `nvim` (Non-Intrusive Completion Toast)

```bash
# Send non-intrusive bottom notification without altering buffer or cursor
SOCK_PATH="/tmp/nvim-herdr-${PROJECT_NAME:-cloud-st}.sock"
nvim --server "$SOCK_PATH" --remote-expr 'luaeval("vim.notify(\"Agent: Refactor complete, Playwriter verification PASS\", vim.log.levels.INFO)")' 2>/dev/null || \
nvim --server /tmp/nvim-herdr.sock --remote-expr 'luaeval("vim.notify(\"Agent: Refactor complete, Playwriter verification PASS\", vim.log.levels.INFO)")' 2>/dev/null || true
```
