---
name: herdr-nvim-qa-workspace
description: Bootstrap and operate a 3-pane Herdr terminal IDE (agent, nvim, qa-runtime) with Neovim silent sovereign editing, Playwriter with-managed browser testing, and inter-panel communication buses. Use when setting up Herdr IDE, linking Neovim with agent, or automating browser QA in terminal.
---

# Herdr Neovim QA Workspace

Organizes terminals into a 3-pane sovereign AI IDE combining coding agent control, silent Neovim human editing, and with-bound Playwriter browser testing.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Herdr Terminal IDE                               │
├──────────────────────────────┬──────────────────────────────────────────────┤
│ [Pane: agent] (宽: 50%)      │ [Pane: nvim] (宽: 50%, 高: 60%)              │
│ - OMP / Claude Code          │ - 人类主权区（绝对静默，防刷屏/防夺焦点）    │
│ - 核心规划、编码、测试       │ - 依赖磁盘 autoread 与 gitsigns 呈现 Diff    │
│ - 接收人类视觉标注图片       ├──────────────────────────────────────────────┤
│ - 执行 Playwriter 验证       │ [Pane: qa-runtime] (高: 40%)                 │
│                              │ - 本地 Dev Server (Vite / Next.js)           │
│                              │ - 基于 with 管理器的 Playwriter 会话池       │
└──────────────────────────────┴──────────────────────────────────────────────┘
```

## Core Invariants

1. **Sovereign editing (Zero-focus-stealing)**: Agent writes files to disk silently; Neovim detects changes via `autoread` and `gitsigns`. Agent MUST NOT issue intrusive remote commands (`:e`, `:checktime`, forced splits) that disrupt human mode or cursor.
2. **With-bound browser lifecycle**: Playwriter sessions MUST run inside context managers guaranteeing immediate deterministic deletion on exit or error.
3. **Named-bus topology**: Panes are strictly addressed by semantic labels (`agent`, `nvim`, `qa-runtime`) rather than transient PTY/pane IDs.
4. **Snapshot-first inspection**: Automated web validation defaults to ARIA accessibility tree (`snapshot`) taking ~50-100 tokens; multimodal images are reserved for human-annotated crops.
5. **No-inline-image protocol (anti-flicker)**: NEVER inline images into the chat transcript (`read` on an image file renders it as a Unicode pixel block that OMP re-renders on every scroll → flicker). Instead:
   - Verification screenshots: save to a file, report the path (human opens via Quick Look); agent confirms content via `file`/dimensions only.
   - Human annotation intake: human captures with Shottr → clipboard; agent runs `pngpaste /tmp/shot.png` and reads it for analysis WITHOUT re-displaying it in the reply.
   - Agent-side page inspection: attach to the live browser via CDP (`terminal-browser` daemon exposes a debugging port) or Playwriter headless — never ask the human to paste screenshots of what CDP can capture directly.
   - Inline an image in the reply ONLY when the human explicitly asks to see it in chat.

## Visual feedback loop (human ⇄ agent)

1. Human views the page in a `terminal-browser` window (standalone Ghostty or the qa-runtime pane).
2. Human circles the problem: Shottr region capture → annotate → Enter (clipboard).
3. Human tells the agent "看剪贴板"; agent: `pngpaste /tmp/shot.png` → multimodal read → cross-locate the DOM node via CDP ARIA snapshot / `elementFromPoint`.
4. Agent fixes source → `scripts/verify-ui.py` regression → saves a verification screenshot to a file and reports the path.

## Fast execution path

1. **Bootstrap Workspace**: In any project directory, execute the bundled bootstrap script:
   ```bash
   scripts/herdr-ide.sh [project-dir] [--new-tab] [--watch]
   ```
2. **Verify Topology**:
   - `herdr pane layout` must confirm 3 semantic panes (`agent`, `nvim`, `qa-runtime`).
   - `nvim` runs with RPC socket at `/tmp/nvim-herdr.sock`.
   - `qa-runtime` runs the dev server or the `qa-watch.sh` daemon.
3. **Dispatch & Collaboration**:
   - Human delegates code blocks in Neovim via `<leader>aa`.
   - QA failure watcher automatically prompts `agent` on test regressions.
   - Playwriter UI verification runs deterministically via `scripts/verify-ui.py`.



## References & Progressive Disclosure

- Read `references/terminal-browser.md` before touching terminal-browser in panes, `kitty_graphics` config, browser shortcuts, or diagnosing a blank/flickering pane.
- Read `references/communication-buses.md` for definitions, Lua handlers, and CLI commands for the 4 inter-panel communication buses.
- Read `references/collaboration-sop.md` for step-by-step SOP on self-healing test loops, visual bug triage, and non-intrusive notifications.
