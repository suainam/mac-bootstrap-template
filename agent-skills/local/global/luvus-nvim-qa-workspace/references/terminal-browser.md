# Terminal-browser integration notes (2026-08-25 session)

Load this file when working with terminal-browser — Herdr supports Kitty Graphics passthrough; Luvus does not (blank pane expected), kitty graphics config, browser shortcuts, or diagnosing blank/flickering panes.

## Config red lines

- **Luvus v0.12.0 has no Kitty Graphics passthrough** (verified: `luvus help` has no `graphic`/`kitty` hit; `luvus pane read` emits ANSI only; CDP `:63346/json/list` alive but pane blank). Do NOT run `terminal-browser` inside a `luvus` pane — use Playwriter headless (`scripts/verify-ui.py`) or a standalone Ghostty / system browser. See `SKILL.md` invariant 6.

- **Herdr: rendering in a pane works** with `[experimental] kitty_graphics = true` in `~/.config/herdr/config.toml`. NEVER flip it off to fix an unrelated symptom — it is the transport that relays kitty graphics frames from pane apps to the host terminal. Known upstream gap: mouse input inside herdr (herdrdev/herdr#2673), rendering itself is fine.
- **Flicker when scrolling chat ≠ kitty graphics.** Images inlined into the agent transcript render as huge Unicode pixel blocks that OMP re-draws on every scroll. Fix is behavioral (Invariant 5 in SKILL.md), not config.

## Shortcuts

- macOS defaults are `super+X`, which a PTY cannot carry — they arrive via the kitty keyboard protocol or terminal-browser's OS-level helper.
- The authoritative binding list is the in-app command palette (`cmd+p`), not the README (main-branch docs vs installed dev build drift).
- Rebind per-launch with `--palette-key/--find-key/--devtools-key/--console-key`.
- `ctrl+t` / `ctrl+l` = new tab / edit URL (hardcoded, ctrl accepted directly).

## Agent channels for an already-open browser

Pick in this order:

1. CDP attach to the daemon's `--remote-debugging-port` (screenshot/eval/ARIA, zero cost to the human).
2. Playwriter headless via `scripts/verify-ui.py`.
3. `pngpaste` for human clipboard annotations.

`herdr pane read` / `luvus pane read` return text/ANSI only — it can NEVER show rendered pixels; do not try.

## Debugging recipes

- `ps -ww -E -p <pane_shell_pid>` dumps the pane env (verify `HERDR_PANE_ID`/`LUVUS_PANE_ID`, `COLORTERM`) without touching the pane.
- `herdr pane run` / `luvus pane send` silently do nothing while a raw-mode app (e.g. terminal-browser) owns the pane foreground — kill it first.
- Controlled diff: run the same command under `script -q /tmp/log` inside vs outside the pane env (`env -u HERDR_PANE_ID …`) and compare the escape-byte streams; this isolated adapter vs PTY vs herdr in minutes.
- A live renderer is verifiable via its CDP port (`curl :PORT/json/list`) even when the pane shows nothing — distinguishes "browser broken" from "drawing broken".

---

## Display Scaling, Cross-Monitor Adaptation & Resize Architecture (PR #75)

Upstream PR: [zenbu-labs/terminal-browser#75](https://github.com/zenbu-labs/terminal-browser/pull/75) (Closes #16, Closes #70).

### 1. PTY Foreground vs Background Daemon Signal Pipeline
- **Root Cause**: The OS kernel delivers `SIGWINCH` (window size change) **only** to the controlling terminal's foreground process group (the CLI client in the pane), **never** to the background detached Electron daemon.
- **Pipeline**:
  1. Terminal pane resizes -> Kernel sends `SIGWINCH` to foreground CLI client.
  2. CLI client forwards `{"cmd":"resize"}` over UNIX socket to the daemon.
  3. `daemon.ts` calls `Session.nudgeResize()`.
  4. `Session.nudgeResize()` must trigger `followCellZoom()` -> `recalculateLayout()` -> `controller.resize()` -> `render()`.
  5. In Rust native engine (`pixel-node`), `watch_resize: tty.is_some()` enables SIGWINCH listening for direct TTY attachments.

### 2. Herdr Cell Metrics & The 1/4 Quadrant Bug (#70)
- **Root Cause**: `Herdr::connect` previously cached `cell_width_px` / `cell_height_px` from `pane.graphics.info` once at startup.
- **Failure Mode**: When moving between a 2x Retina display (`16x32` cell) and a 1x monitor (`8x16` cell), `Herdr::present` divided canvas dimensions by the stale 16x32 divisor (`grid_cols = width / 16`, `grid_rows = height / 32`), placing the canvas in a $1/2 \times 1/2 = 1/4$ quadrant in the top-left corner.
- **Fix**:
  - `Herdr.cell` upgraded to `(NonZeroU32, NonZeroU32)` (Rust type-level safety, zero division-by-zero risk).
  - `Terminal::draw()` dynamically queries `self.cell_size()` before presenting frames and calls `herdr.update_cell(cell)`.

### 3. Live Chromium DPI Rasterization via CDP (#16)
- **Root Cause**: In Electron offscreen rendering, `window.setContentSize()` updates CSS logical bounds, but Chromium's internal offscreen rasterizer `deviceScaleFactor` remains stuck at construction time unless overridden.
- **Fix**:
  - `BrowserController.resize()` and `DevtoolsWindow.resize()` synchronize Chromium's rasterizer via CDP `Emulation.setDeviceMetricsOverride({ width, height, deviceScaleFactor: renderScale, mobile: false })`.
  - Serialized via `private resizeSeq = 0` to prevent async promise attach race conditions.

### 4. Zero-Flicker Drag Resizing
- **Root Cause**: `controller.ts` called `this.surface.clear()` unconditionally on every resize event, creating a 60Hz black strobe flicker during mouse drag.
- **Fix**: Preserved previous frame texture during resize (`if (options?.keepFrame === false) this.surface.clear()`), letting the engine scale the previous texture smoothly until the new frame is painted.

### 5. Upstream Tracking & Release Update
- Local binaries are patched and built from `/tmp/tb-src`.
- Once upstream merges PR #75 and cuts a new release (`v0.7.0+`):
  ```bash
  terminal-browser upgrade
  ```
  And verify via `terminal-browser --version` and `curl 127.0.0.1:<CDP_PORT>/json/list`.
