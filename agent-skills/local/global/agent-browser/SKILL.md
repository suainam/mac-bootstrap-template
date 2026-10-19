---
name: agent-browser
description: Vercel Labs browser automation CLI (agent-browser) with named sessions, real Chrome profile reuse, accessibility-tree refs, page-context eval, and network capture. Use for web navigation, form filling, screenshots, scraping, UI testing, or logged-in enterprise portals. For cross-origin iframe JavaScript, use OMP eval browser with tab.run and page.frames().
---

# agent-browser

Drive Chrome via `agent-browser` (vercel-labs, 44.2k★) — a Rust CLI talking CDP directly, no Playwright/Puppeteer dependency. Snapshots return compact `@eN` refs instead of raw HTML.

**Before first use**, read the version-matched built-in guide:

```bash
agent-browser skills get core --full
```

## 1. Core loop

```bash
export AGENT_BROWSER_SESSION="$(agent-browser session id --scope worktree --prefix task)"

agent-browser open https://example.com   # navigate
agent-browser snapshot -i                # interactive elements with @eN refs
agent-browser click @e3                  # act on a ref
agent-browser snapshot -i                # re-snapshot after any change
agent-browser close
```

The default unnamed session is shared with every agent on the machine and persists across conversations. Always set a named session.

## 2. Real Chrome profile (logged-in cookies / SSO)

```bash
agent-browser --session portal \
  --profile Default \
  --executable-path '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
  open https://internal-portal.example.com

agent-browser --session portal snapshot -i
agent-browser --session portal close
```

- `--profile <name|path>` accepts a Chrome profile name (`Default`, `Profile 1`) under `~/Library/Application Support/Google/Chrome/`, or a directory path for a persistent custom profile.
- `--executable-path` selects the real Chrome binary; without it the bundled Chrome for Testing is used (no login state).
- `--auto-connect` attaches to an already-running Chrome instead, reusing its auth state.
- `--restore` persists cookies/localStorage across daemon restarts.

Verify setup: `agent-browser doctor` (Chrome path, profiles, daemon, security).

## 3. Page-context eval

`eval` runs JavaScript **in the page**, like the DevTools console — there is no `page` object:

```bash
cat <<'EOF' | agent-browser eval --stdin
const rows = document.querySelectorAll("table tbody tr");
Array.from(rows).map(r => ({ name: r.cells[0].innerText, price: r.cells[1].innerText }));
EOF
```

Prefer `--stdin` (heredoc) or `-b <base64>` over inline quoting.

## 4. Frames

`frame` switches **ref/text resolution context** for subsequent commands, not the JS eval context:

```bash
agent-browser snapshot              # iframe appears as [ref=e2]
agent-browser frame 'iframe'        # switch into it
agent-browser snapshot -i           # refs now resolve inside the frame
agent-browser get text 'h1'         # works only when the frame is same-origin / opted in
agent-browser frame main            # back to top
```

Cross-origin frames block both snapshot contents and eval (verified: `frame` succeeds, `eval` still returns the parent document's values). Use `get text` when the tree is exposed; otherwise use the OMP fallback below.

## 5. Network capture (auth tokens, API payloads)

```bash
agent-browser network requests --type xhr,fetch --json
agent-browser network request <requestId> --json     # full headers + body
agent-browser network har start ./trace.har          # record a HAR
```

`network requests --json` already includes request headers, so an `Authorization` header can be read without monkey-patching `XMLHttpRequest`.

## 6. OMP eval `browser` fallback (cross-origin iframe JS)

When a script needs `page.frames()` / cross-origin `evaluate`, use OMP's in-process browser instead of the CLI:

```javascript
// OMP eval, language="js"
const tab = await browser.open({
  name: "devops",
  url: "https://devops.example.com/#/story/list",
  app: { tern: false },      // full Chromium mode: page.frames() works
});
const result = await tab.run(`
  const f = page.frames().find(fr => fr.url().includes("pmp.example.com"));
  if (!f) return { error: "frame missing", urls: page.frames().map(fr => fr.url()) };
  return await f.evaluate(() => Array.from(document.querySelectorAll("tr")).map(r => r.innerText));
`);
await tab.close();
```

- `app: { tern: false }` = full Chromium; `page` is Puppeteer-like (`frames()`, `evaluate()`, `click()`, `url()`).
- `app: { relay: true }` attaches to the user's real Chrome through the OMP relay extension (logged-in profile).
- Tern PiP mode (`tab.observe()`) is lighter but has no `page.frames()`.

## Choosing a path

| Need | Use |
|---|---|
| Interactive navigation, clicks, forms, screenshots | agent-browser CLI |
| Logged-in enterprise portal | `--profile` + `--executable-path` (or `--auto-connect`) |
| Read an auth header from live traffic | `network requests --json` |
| Cross-origin iframe JS evaluate | OMP `browser.open` + `tab.run` |
| Multi-step Node/Python driver with `page` API | OMP `tab.run` |

## References

- [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser)
- `brew install agent-browser`; setup check via `scripts/install-agent-browser.sh`
- Built-in docs: `agent-browser skills get core --full`
