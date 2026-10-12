---
name: jev-browser-use
description: Browser automation with persistent named pages and TypeSafe Jev action loops via jev-browser-use CLI (plus OMP eval browser fallback). Use when navigating websites, filling forms, taking screenshots, scraping, testing web UI, or automating logged-in Chrome tabs via extension relay.
---

# jev-browser-use

Control a persistent Chrome browser via `jev-browser-use` warm daemon, TypeSafe Jev System One action loops (`page.jev()`), or OMP's native `eval` `browser` fallback.

## 1. Quick CLI & Script Usage (No Jev Key Required)

Named pages (`browser.getPage("<name>")`) persist across CLI invocations inside the warm daemon:

```bash
# Headless snapshot & inspection
jev-browser-use --headless <<'JS'
const page = await browser.getPage("main");
await page.goto("https://example.com");
await page.snapshot({ interactive: true });
JS

# Single-line evaluation
jev-browser-use --headless -e 'const p = await browser.getPage("main"); await p.click("ref/e1"); await p.waitForLoad(); await p.url()'

# Stop the automation daemon when finished
jev-browser-use stop
```

## 2. Chrome Extension Mode (Reuse Logged-In Profile)

To drive your existing Chrome profile with active cookies/SSO sessions:

1. **Load Unpacked Extension** (one-time):
   - Open `chrome://extensions`, enable **Developer mode**, click **Load unpacked**, and select `~/.jev-browser-use/v1/extension` (installed by `scripts/install-jev-browser-use.sh`).
2. **Start Relay**:
   - Run `jev-browser-use relay` (listens on `127.0.0.1:9222`) and toggle **Active** in the **jev-browser-use** extension popup (`Connected to relay`).
3. **Connect CLI / Scripts**:
   ```bash
   jev-browser-use --connect http://127.0.0.1:9222 -e 'const p = await browser.getPage("main"); await p.goto("https://example.com"); await p.title()'
   ```
   - The extension creates an isolated `jev-browser-use` tab group sharing your profile's login state while keeping unrelated tabs untouched.

## 3. TypeSafe Jev Action Loop (`page.jev`)

When `TYPESAFE_API_KEY` is exported in the environment, delegate multi-step navigation, dropdown selection, autocomplete, and form filling to Jev (`~150–300ms` per decision, zero text generation):

```bash
jev-browser-use --headless -t 60 <<'JS'
const p = await browser.getPage("demo");
await p.goto("https://the-internet.herokuapp.com/dropdown");
await p.jev({
  action: "run",
  goal: "Choose Option 2 from the dropdown",
  until: { fields: [{ label: "Please select an option Option 1 Option 2", value: "2" }] }
});
JS

# Always independently verify the final DOM state (`verified` is always false):
jev-browser-use --headless -e 'const p = await browser.getPage("demo"); await p.$eval("select", e => e.value)'
```

### Key Jev Primitives & Contracts

- **Pre-bound `inputs`**: Pass known field values up front (`inputs: [{ url: "https://...", label: "Search", text: "query" }]`) so Jev types without pausing for a host turn.
- **Deterministic `until` Checkpoint**: Specify target `url`, visible `text`, `fields`, or `rows` so the daemon stops immediately when met without an extra Jev API call.
- **Single-Submission `completion` Guard**: Use `completion: { submitLabel: "Save", after: { text: ["Saved"] } }` to guarantee at most one click on a submit/save button.
- **Conditional `plan`**: For known multi-stage forms, compile a `plan` (`origins`, `targets`, `stages`) so grounded actions execute locally with **0 Jev API calls**, falling back to Jev only for semantic target resolution.
- **Handoffs (`needs_text` / `needs_host`)**: If Jev encounters an unbound text field or low-confidence/unsupported control, it returns `sessionId` and `requestId`. Supply the text or resolve the control in the host agent, then call `action: "resume"`.

## 4. OMP Native `eval` `browser` Fallback

When running inside OMP (`oh-my-pi`) and `jev-browser-use` is unavailable or a quick in-process inspection is preferred, use OMP's built-in `eval` `browser` global (no subprocess spawn per step):

```javascript
// In OMP eval (language="js"):
// Headless / Tern PiP mode:
const tab = await browser.open({ name: "qa", url: "http://localhost:5173" });
const observed = await tab.observe();
await tab.close();

// Existing Chrome via OMP relay:
const targets = await browser.targets({ app: { relay: true } });
const liveTab = await browser.open({ name: "hpm", app: { relay: true, target: "/achievement" } });
```
