# OpenCode driver — §5a, §5c, §6a, §6c, §6d, §6g, §6h (OMP edition)

OpenCode-specific driver for `dispatch-opencode`.
Differences from Codex:
- No `/goal` mode — nudge-driven execution: supervision sweep sends continuation prompt each turn until DONE
- Safe default posture: runs without `--auto` by default; approvals handled via supervised interaction unless `--auto`/`--yolo` explicitly authorized
- Real native session identity: reported directly by Herdr in `agent_session.value` (`ses_...`) and via `opencode session list`
- Native resume: `opencode -s <session-id>` or `opencode --continue`
- No speculative probes: no rollout JSONL tail or SQLite WAL hacking

---

## §5a Pre-flight the pane

Run in the lane's pane:

    herdr pane run <pane> "opencode --version"

Then poll `herdr pane read <pane> --source visible` (not `--source` alone; not `wait-output`).

- `opencode` not found or version fails → stop that lane, report it.
- Dependencies missing → run the repo's install command in the pane before `agent start`.
- `.env` / secrets missing → **ask the user** whether to symlink them. Never copy secrets.

Then write the brief (§5b in plan.md) before launching.

---

## §5c Launch OpenCode and send initial prompt

**Default posture (Safe):**
Launch without approval bypass:

    herdr agent start <lane> --kind opencode --pane <pane> --timeout 60000

**Bypass posture (Only if explicitly passed `--auto` or `--yolo`):**

    herdr agent start <lane> --kind opencode --pane <pane> --timeout 60000 -- --auto

*Note: Never pass `--no-auto-sharing` — OpenCode does not recognize this flag.*

**Three disclosure lines §3 owes the user:**
- Approval posture: `默认安全模式（需手动确认权限）` 或 `--auto（已显式启用自动批准权限）`
- Drive mode: `单次提示+循环续跑（无 goal 模式）：每轮需要监督循环主动续跑`
- Rate limits: `所有 lane 共享同一个 OpenCode 账号/配置，速率窗口共享，可能同时限流`

**Verify readiness before sending prompt:**
Wait for OpenCode to start and show its composer:

    herdr agent read <lane> --source visible

If a directory trust dialog appears, send Enter:

    herdr agent send-keys <lane> enter

When the prompt composer is ready, send the initial prompt:

    herdr agent prompt <lane> "Read .dispatch/TASK.md in this directory and work through its checklist step by step. Keep .dispatch/progress.md updated after every item. Write .dispatch/DONE when everything is finished and verified, then run the notify-back command TASK.md gives you."

Record the lane as phase `implementing`.
Retrieve native session ID once the session initializes:

    herdr agent get <lane> | jq -r '.result.agent.agent_session.value'

(Fallback: `cd <checkout> && opencode session list | head -1 | awk '{print $1}'`).
Record the session id (e.g. `ses_f0f5...`) in the state file for native resumption.

Start every lane before supervising any.

---

## §6a Probe one lane

OpenCode does not use Codex rollout files. Probe reads native Herdr agent state and directory status:

1. **Session id**:
   Read native session identity from Herdr:
   `herdr agent get <lane> | jq -r '.result.agent.agent_session.value'`
   If null before first prompt finishes, fallback to:
   `opencode session list` run in `<checkout>`.

2. **turn_state & agent_status**:
   Query `herdr agent get <lane>`:
   - `idle` or `done` → `turn_state = complete` (turn settled)
   - `working` → `turn_state = working`
   - `blocked` → `turn_state = blocked`

3. **used_pct**:
   `null` (OpenCode does not expose remaining context window machine-readably from outside).

4. **compactions**:
   `0` (no automatic compaction counter).

5. **goal_status** / **goal_tokens**:
   `null` (OpenCode has no goal mode).

Probe contract summary:
```json
{
  "session_id": "ses_...",
  "turn_state": "complete" | "working" | "blocked",
  "used_pct": null,
  "compactions": 0,
  "goal_status": null,
  "goal_tokens": null
}
```

---

## §6c Classify each lane, in this order

| Class | Test | Action |
| --- | --- | --- |
| `terminal` | phase is `published`, `failed`, user-paused, or `verified` with recorded §6f degrade reason | Skip |
| `unpublished` | phase `verified`, `push_attempts` < 3, no degrade reason, `pushed_sha` missing or behind branch HEAD, or `pr_url` missing with push enabled | Retry publish (§6f) |
| `done` | `.dispatch/DONE` exists **and** `turn_state == complete` | Verify (§6e); parent independently validates acceptance criteria. False DONE rejected! |
| `blocked` | `agent_status == blocked` or approval overlay visible | Read `--source visible`, handle (§6g) |
| `stalled` | `state_change_seq` unchanged ≥ 15 min, and no DONE | Read `--source visible` once; resolve if modal; `idle_incomplete` if composer idle; else escalate |
| `idle_incomplete` | `agent_status` in [`idle`, `done`], no DONE file | Primary continuation engine: read progress.md, send continuation prompt (§6d) |
| `working` | otherwise | Leave alone |

`unknown` `agent_status` is an anomaly to surface, never a completion.

---

## §6d Steer an idle_incomplete lane (Nudge mechanism)

OpenCode is nudge-driven. When `turn_state == complete` (agent is idle or done) but `.dispatch/DONE` has not
been written:

1. Read `<checkout>/.dispatch/progress.md` to see what item the lane last worked on.
2. Read `git -C <checkout> status --porcelain` and `git -C <checkout> log -1 --oneline` to confirm activity.
3. Check nudge count in state file:
   - If nudge count < 5: send continuation prompt:
     ```bash
     herdr agent prompt <lane> "Continue working through .dispatch/TASK.md. Update .dispatch/progress.md after completing each checklist item. When all criteria pass, write .dispatch/DONE and trigger notify-back."
     ```
     Increment nudge count, set state to `implementing`.
   - If nudge count >= 5 with no new commits and no progress.md changes: escalate to user.

---

## §6g Handle a blocked lane

When `agent_status` is `blocked` or an interactive prompt overlay is visible:

1. Read `--source visible`:
   ```bash
   herdr agent read <lane> --source visible
   ```
2. Identify the approval request:
   - Directory trust dialog: send Enter via `herdr agent send-keys <lane> enter`
   - Safe in-tree file edit or test execution: send `y` or Enter to approve
   - Out-of-tree / dangerous action (network egress, credential read, git push, force operations):
     **Do not answer**; pause lane, record in state, surface to user.

---

## §6h Compact / Native Resume a lane

If OpenCode context needs compaction:
OpenCode supports the `/compact` slash command:

    herdr agent prompt <lane> "/compact" --wait --until idle --timeout 120000

To interrupt an in-flight turn:
Send double escape:

    herdr agent send-keys <lane> esc esc

To exit OpenCode cleanly:

    herdr agent prompt <lane> "/exit"

**Native session resume:**
Resume the recorded session on the same pane:

    herdr agent start <lane> --kind opencode --pane <pane> --timeout 60000 -- -s <session-id>

(Or pass `--continue` to continue the latest session in `<checkout>`).
Herdr immediately re-detects the agent and verifies `agent_session.value == <session-id>`.
