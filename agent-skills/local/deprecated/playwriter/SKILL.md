---
name: playwriter
description: Control user's Chrome browser or headless Chromium for web automation, form filling, scraping, and inspection using Playwright snippets and accessibility snapshots.
---

# Playwriter

Control Chrome browser via Playwright snippets. Connects to the user's running Chrome (via extension/CDP) or launches headless Chrome.

## Quick CLI Usage

```bash
# 1. Start a session
SESSION_ID=$(playwriter session new --browser headless | grep -oE 'Session [0-9]+' | awk '{print $2}')

# 2. Execute Playwright JavaScript snippet
playwriter -s "$SESSION_ID" -e 'await page.goto("https://example.com"); console.log(await snapshot({ page }))'

# 3. Clean up session when done
playwriter session delete "$SESSION_ID"
```

## Running Chrome Connection Modes

1. **Extension Mode (Default)**:
   - User clicks the Playwriter Chrome extension icon on the target tab (icon turns green).
   - Reuses current user cookies, session tokens, and local state.
2. **Headless Mode**:
   - `playwriter session new --browser headless`
   - Fully autonomous, no extension or user interaction needed.
3. **Direct CDP Mode**:
   - `playwriter session new --direct` or `playwriter session new --direct ws://localhost:9222/...`
   - Connects directly to Chrome remote debugging port.

## Context Variables in `-e`

- `page`: Active Playwright Page instance.
- `context`: Active BrowserContext.
- `state`: Persistent dictionary scoped to the current session across multiple `-e` calls.
- `snapshot({ page })`: Compact accessibility tree with `aria-ref` locators (fast, token-efficient).
- `getLatestLogs({ page, sinceLastCall: true })`: New browser console errors and logs.

## Best Practices

- Always wrap `-e` code in single quotes: `playwriter -s "$SESSION" -e '...'`.
- Prefer `snapshot({ page })` over raw screenshots to save context tokens.
- Check page state after actions: **Observe → Act → Observe**.
