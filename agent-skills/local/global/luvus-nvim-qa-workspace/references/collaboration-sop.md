# Tri-Pane Collaboration SOP Reference

## 1. Self-Healing QA Watcher Loop

```
[QA Watcher in qa-runtime]
       │ (Detects test failure / error output)
       ▼
[Loop Guard Check] ──(Exceeds 3 consecutive failures?)──► [Pause & Log Alert]
       │ No
       ▼
[Dispatch Prompt to Agent]
`herdr agent prompt agent "【QA 自动报警 #N】测试失败，请修复: ..."`
       │
       ▼
[Agent Receives Task]
1. Reads failure log & stack trace
2. Edits source files (writes silently to disk)
3. Neovim displays changes silently via gitsigns
       │
       ▼
[QA Watcher Re-runs]
- If Green: resets failure counter to 0, logs recovery
- If Red: increments counter up to max 3
```

## 2. Visual Bug Triage with Multimodal Feedback

1. **Human Spots Visual Bug**: In real browser or local dev server.
2. **Capture & Annotate**: Uses system screenshot / CleanShot to crop flawed component and draw red bounding box $\to$ saved to `/tmp/bug.png`.
3. **Dispatch Prompt**:
   ```bash
   herdr agent prompt agent "请参考视觉标注修复布局问题: local:///tmp/bug.png"
   ```
4. **Agent Resolution**:
   - Reads image multimodal features
   - Calls `scripts/verify-ui.py` to inspect live ARIA snapshot & CSS
   - Edits component styles
   - Verifies hot reload without altering human Neovim cursor.

## 3. Playwriter QA Verification SOP

Agent executes `scripts/verify-ui.py` to validate page health:

```bash
# Verify default Vite port (5173)
python3 scripts/verify-ui.py http://localhost:5173

# Or on custom backend port
python3 scripts/verify-ui.py http://localhost:3000
```

- **Pass condition**: ARIA tree contains expected elements, `getLatestLogs()` contains zero unhandled exceptions.
