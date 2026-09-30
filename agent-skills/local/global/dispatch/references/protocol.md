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
   ```bash
   PANE=$(herdr worktree create --cwd <repo> --branch <branch> --label <name> --no-focus | jq -r '.result.root_pane.pane_id')
   herdr agent start <name> --kind <kind> --pane "$PANE" --timeout 60000 -- <args>
   sleep 2
   VISIBLE="$(herdr pane read "$PANE" --source visible)"
   if echo "$VISIBLE" | grep -qE "trust|Trust|Accessing workspace|trust this folder"; then
     herdr pane send-keys "$PANE" enter
     sleep 1
   fi
   ```
2. **Readiness Gate**:
   Assert that `interactive_ready: true` AND the real composer prompt is rendered:
   - Claude: `❯ `
   - Codex: `› Ask Codex to do anything`
   - Agy: `> `
   - OpenCode: `Ask anything...`
3. **Step 2: Prompt Injection**:
   Only after passing the readiness gate, inject the task:
   ```bash
   herdr agent prompt <name> "Read .dispatch/TASK.md and work through it..."
   ```

---

## 2. Standardized Notify-Back + Handoff Signature

Every child agent writes `.dispatch/DONE` plus a standard Handoff file, then notifies. The signature MUST encode origin coordinates plus handoff pointer:

$$\text{Signature} = \left[\langle\text{pane\_id}\rangle\_\langle\text{agent\_kind}\rangle\_\langle\text{repo\_slug}\rangle\right] + \text{Handoff path}$$

### Exact Multi-Line Specification:
```bash
mkdir -p ~/Documents/handoffs
# Assert handoff exists, then notify:
test -s "${HOME}/Documents/handoffs/${HANDOFF_FILENAME}" && \
herdr agent prompt <orch-pane> "\n[NOTIFY] [<pane_id>_<agent_kind>_<repo_slug>]\nDONE: <one-liner core conclusion>\nHandoff: ~/Documents/handoffs/${HANDOFF_FILENAME}"
```

### Example Rendered Notification:
```text
[NOTIFY] [w3:pAY_opencode_auroraops-control]
DONE: PR #120 created, squashed and merged, unit tests 100% pass
Handoff: ~/Documents/handoffs/auroraops-control-releaser-handoff-20260930_164500.md
```

*Benefits:*
- Distinct 3-line format prevents notifications from blending with terminal prose.
- First line identifies origin; second line yields the decisive outcome; third line gives the direct file pointer.
---

## 3. Fire-and-Yield Handoff Principle

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
