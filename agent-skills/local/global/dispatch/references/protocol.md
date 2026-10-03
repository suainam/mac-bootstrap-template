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
   Only after passing the readiness gate, dispatch through the unified bus. The request MUST bind the evaluated `ORCH_PANE` coordinate so the child reports to the exact parent:
   ```bash
   python3 "$GATE" --repo "$REPO_ROOT" dispatch \
     --task "<task-file>" --lane-name "<wave>-<lane>-<slug>" \
     --target "$WORKER_PANE" --callback-target "$ORCH_PANE"
   ```
   *(CRITICAL: formal dispatch never calls raw `herdr agent prompt`; an unresolved or nonexistent callback pane is refused before delivery.)*

   > **Never hand-quote the callback.** The historical form
   > `herdr agent prompt ${ORCH_PANE} '\n[NOTIFY] ...'` is a trap: bash single
   > quotes do not expand escapes, so `\n` reaches the worker as two literal
   > characters and the entire report renders as one long single line. This file
   > shipped that form for a long time. Report back with the exact callback
   > command carried by `[DISPATCH]`; it uses `dispatch_plugin.py notify`
   > with the stable run/dispatch identity, renders the standard layout, and
   > cannot be mis-quoted.
---

## 2. Standardized Notify-Back & Precision Coordinate Signature

Every child agent writes `.dispatch/DONE` plus a structured Handoff file, then notifies the orchestrator.

### Redline: Second-Level Precision Handoff Timestamp
Never use day-only dates (`%Y%m%d`) which cause overwrites and collision across multiple runs on the same day.
**MANDATORY**: Timestamps MUST use second-level precision: `$(date +%Y%m%d_%H%M%S)`.

$$\text{Handoff Path} = /\text{tmp/handoff/}\langle\text{repo\_slug}\rangle-\langle\text{name}\rangle\text{-handoff-}\mathbf{YYYYMMDD\_HHMMSS}\text{.md}$$

### Exact Multi-Line Specification:
```bash
HANDOFF_TS="$(date +%Y%m%d_%H%M%S)"
HANDOFF_FILENAME="${REPO_SLUG}-${NAME}-handoff-${HANDOFF_TS}.md"
mkdir -p "/tmp/handoff"

# Assert handoff exists, then use the exact callback command from [DISPATCH]:
test -s "/tmp/handoff/${HANDOFF_FILENAME}" && \
python3 dispatch_plugin.py notify \
  --signature "<lane_id>_<worker_pane>" \
  --run-id "<run-id>" --dispatch-id "<dispatch-id>" \
  --done "<one-liner core conclusion>" \
  --handoff "/tmp/handoff/${HANDOFF_FILENAME}" \
  --target "<orch-pane>" --send
```

### Example Rendered Notification:
```text
[NOTIFY] [1-2_w3:pAY]
Run ID: run-0123abcd
Dispatch ID: dispatch-89abcdef
DONE: lane completed its assigned verification
Handoff: /tmp/handoff/1-2-review-handoff-20260930_164500.md
```

---

## 2b. Stage Heartbeat (`[HEARTBEAT]`) — liveness, not results

A long lane that says nothing is indistinguishable from a crashed one, and an
impatient orchestrator will either take the work over or re-run it. A heartbeat
is the cheap fix: periodic, structured evidence that the worker is alive **and
where it is**.

### The distinction that makes this safe

| Marker | Means | Ends the orchestrator's park? |
| --- | --- | --- |
| `[HEARTBEAT]` | "still working, here is where" | **No** — absorbed silently |
| `[NOTIFY]` | "finished, here is the result" | **Yes** — the only routine wake |

A heartbeat must **never** be treated as a result. Ending the park on one hands
the orchestrator its own work mid-flight, which is exactly the false-busywork
loop the park exists to prevent.

### When to send

Send a heartbeat when **either** condition holds:

- the task has been running longer than **3 minutes**; or
- the worker has **crossed a milestone stage**.

At most one per 3 minutes per lane. The current orchestrator stall threshold is
**3 minutes** (`STALL_THRESHOLD_MS = 3 × 60s`). A heartbeat inside that window
refreshes only its own lane; after restart the persisted `last_heartbeat`
continues to count as liveness evidence.

### Signature
```text
\n[HEARTBEAT] [<pane_id>_<agent_kind>_<repo_slug>]
STAGE: <current milestone, e.g. "Stage 4 Deploying on target">
STATUS: <key diagnostic or progress summary>
PROGRESS: <percentage or N/M>
```

Use the guarded prompt transport with resolved pane ids; do not send a raw
`herdr agent prompt` heartbeat:

```bash
$PY multiplexer/herdr-dispatch/bin/dispatch_plugin.py prompt \
  --text "\n[HEARTBEAT] [w3:p6_opencode_mac-bootstrap]\nSTAGE: <stage>\nSTATUS: <status>\nPROGRESS: <N/M>" \
  --send --target w3:p1 --allow-no-callback
```

### Example
```text
[HEARTBEAT] [w3:p6_opencode_mac-bootstrap]
STAGE: Stage 4 Deploying on target
STATUS: past the submodule gate, running the playbook directly
PROGRESS: 4/7
```

### What the orchestrator does with it

1. **Absorbs silently** — no steer back to the worker, no wake.
2. **Refreshes the ledger** — writes `last_heartbeat`, `current_stage`,
   `last_status` and `progress_pct` onto that lane.
3. **Resets that lane's stall watchdog** — and only that lane's, so one chatty
   lane cannot mask a genuinely dead one.
4. **Republishes the sidebar token** — the stage is compacted for display
   (`Stage 4 Deploying on hk216` → `dstate: s4@hk216`), so a human can see the
   work is live without asking.

Lifecycle observation is read through `herdr agent get`. An explicit
`agent_not_found` is distinguishable from a query/socket/JSON failure. The
latter is **unknown / recovery-required**: it remains visible and keeps the
claim held; it is never silently converted into orphan/released state.

### Progress values

`PROGRESS` is optional and is never coerced. Anything unparseable (`?`,
`unknown`, `about half`) is recorded as *unknown* rather than `0` — reporting a
false 0% is worse than reporting nothing.

---


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
