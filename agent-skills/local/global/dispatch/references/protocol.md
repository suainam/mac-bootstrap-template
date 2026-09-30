# Dispatch Protocol: Two-Step Handshake & Standardized Notify-Back

## 1. Two-Step Trust Handshake Protocol

When an interactive CLI agent (Claude, Codex, Agy, OpenCode) starts in a newly created worktree, it frequently halts on a workspace trust or permission onboarding prompt:
- Claude: `Accessing workspace: ... Quick safety check: Is this a project you created or one you trust?`
- Agy: `Accessing workspace: ... Do you trust the contents of this project? > Yes, I trust this folder`
- Codex: Tool approval or sandbox access confirmation.

**The Failure Mode**:
Sending `herdr agent prompt` immediately after `agent start` causes the prompt bytes to be consumed as the answer to the modal, discarding the entire task prompt.

**The Protocol**:
1. **Step 1: Start & Resolve Modals**:
   Launch using the verified CLI flags for the bare agent executable:
   - **OpenCode**: `herdr agent start <name> --kind opencode --pane "$PANE" --timeout 60000 -- --auto`
     *(Note: Bare `opencode` launches the interactive TUI and does NOT take `-m` or `--model`. Pass `--auto` to auto-approve).*
   - **Claude Code**: `herdr agent start <name> --kind claude --pane "$PANE" --timeout 60000 -- --model <model> [--dangerously-skip-permissions]`
   - **Antigravity (Agy)**: `herdr agent start <name> --kind agy --pane "$PANE" --timeout 60000 -- --model <model> [--dangerously-skip-permissions]`
   - **Codex**: `herdr agent start <name> --kind codex --pane "$PANE" --timeout 60000 -- -m <model>`

2. **Inspect-on-Failure Gate**:
   If `agent start` returns an error, times out, or fails to detect:
   **MANDATORY**: Run `herdr pane read "$PANE" --source visible` immediately! Inspect the real stderr/crash output. Never blindly retry or run arbitrary commands without diagnosing the pane failure.

3. **Modal Resolution & Readiness Gate**:
   ```bash
   VISIBLE="$(herdr pane read "$PANE" --source visible)"
   if echo "$VISIBLE" | grep -qE "trust|Trust|Accessing workspace|trust this folder"; then
     herdr pane send-keys "$PANE" enter
     sleep 1
   fi
   ```
   Assert that `interactive_ready: true` AND the real composer prompt is rendered:
   - Claude: `❯ `
   - Codex: `› Ask Codex to do anything`
   - Agy: `> `
   - OpenCode: `Ask anything...`

4. **Step 2: Prompt Injection with Explicit Orchestrator Coordinate Binding**:
   The orchestrator MUST explicitly obtain its own pane ID before dispatching:
   ```bash
   ORCH_PANE="$(herdr pane current | jq -r '.result.pane.pane_id')"
   ```
   Only after passing the readiness gate, inject the task. The prompt MUST bind this explicit `ORCH_PANE` coordinate so the child agent notifies the exact parent, never guessing or misrouting:
   ```bash
   herdr agent prompt <name> "Read <task-file> (or .dispatch/TASK.md) and execute. When complete, write ~/Documents/handoffs/<name>-handoff.md and run:
   herdr agent prompt ${ORCH_PANE} '\n[NOTIFY] [<pane_id>_<agent_kind>_<repo_slug>]\nDONE: <one-liner conclusion>\nHandoff: ~/Documents/handoffs/<name>-handoff.md'"
   ```
   *(CRITICAL: If the orchestrator uses a placeholder `<orch-pane>` without substituting its actual `herdr pane current` ID, the child agent either sends to a broken placeholder or misroutes to the human user / sibling panes).*
---

## 2. Standardized Notify-Back & Precision Coordinate Signature

Every child agent writes `.dispatch/DONE` plus a structured Handoff file, then notifies the orchestrator.

### Redline: Second-Level Precision Handoff Timestamp
Never use day-only dates (`%Y%m%d`) which cause overwrites and collision across multiple runs on the same day.
**MANDATORY**: Timestamps MUST use second-level precision: `$(date +%Y%m%d_%H%M%S)`.

$$\text{Handoff Path} = \sim/\text{Documents/handoffs/}\langle\text{repo\_slug}\rangle-\langle\text{name}\rangle\text{-handoff-}\mathbf{YYYYMMDD\_HHMMSS}\text{.md}$$

### Exact Multi-Line Specification:
```bash
HANDOFF_TS="$(date +%Y%m%d_%H%M%S)"
HANDOFF_FILENAME="${REPO_SLUG}-${NAME}-handoff-${HANDOFF_TS}.md"
mkdir -p "${HOME}/Documents/handoffs"

# Assert handoff exists, then notify:
test -s "${HOME}/Documents/handoffs/${HANDOFF_FILENAME}" && \
herdr agent prompt <orch-pane> "\n[NOTIFY] [<pane_id>_<agent_kind>_<repo_slug>]\nDONE: <one-liner core conclusion>\nHandoff: ~/Documents/handoffs/${HANDOFF_FILENAME}"
```

### Example Rendered Notification:
```text
[NOTIFY] [w3:pAY_opencode_example-repo]
DONE: PR #120 created, squashed and merged, unit tests 100% pass
Handoff: ~/Documents/handoffs/example-repo-releaser-handoff-20260930_164500.md
```

---

## 3. Convergence & Skeptic Re-work Loop (Diamond Pattern)

When a **Skeptic** reviewer finishes its independent adversarial review:
1. **Did Skeptic uncover defects?**
   - **YES**: The Orchestrator routes the review findings back to the **Writer** (the original implementation worker in the code worktree) to fix the defects (e.g. version skew, missing env keys). The Orchestrator does NOT terminate or skip to merge.
   - **NO**: All tests pass and no defects remain $\rightarrow$ Proceed to **Human Gate** for push/PR authorization.
2. **Orchestrator Transparency Redline**:
   Whenever routing review findings back to the Writer, the Orchestrator MUST broadcast a one-line progress update to the Human user, stating what Skeptic found and why re-work is triggered.

---
## 4. Fire-and-Yield Handoff Principle

The Orchestrator MUST NEVER run blocking waits or polling loops on the main session thread.

- **Bad**: Dispatch task $\rightarrow$ run `herdr agent wait` or `while sleep 10` $\rightarrow$ blocks human typing $\rightarrow$ user inputs become "interruptions".
- **Good**: Dispatch task $\rightarrow$ configure notify-back $\rightarrow$ **yield control immediately** $\rightarrow$ main session stays responsive $\rightarrow$ child agent wakes parent via Herdr IPC prompt-back.

---

## 4. Proxy Environment Defensive Sanitization

Stale or unroutable proxy environment variables (`http_proxy`, `https_proxy`, `all_proxy`, `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`) frequently cause `gh` CLI commands, git push/fetch operations, and GitHub Actions triggers to hang on TLS handshake timeouts.

**The Defensive Pattern**:
When executing network-sensitive operations in automated scripts or instructing child agents:
```bash
env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY gh ...
```
Isolate network traffic from broken local proxy routes by default.
