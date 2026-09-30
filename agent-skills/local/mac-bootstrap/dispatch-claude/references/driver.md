# Claude Code driver — §5a, §5c, §6a, §6c, §6d, §6g, §6h (OMP edition)

Adapted for Claude Code under Herdr in mac-bootstrap.

---

## §5a Pre-flight the pane

Run in the lane's pane:

    herdr pane run <pane> "claude --version"

Then poll `herdr pane read <pane> --source visible`.

- `claude` not found or version fails → stop that lane, report it.
- Dependencies missing → run install in pane before `agent start`.
- `.env` / secrets missing → ask user whether to symlink. Never copy secrets.

Write the brief (§5b in `references/plan.md`) before launching.

---

## §5c Launch Claude Code and prompt

Launch with `--kind claude` in Herdr. Default posture uses safe permissions (manual approval handling):

    herdr agent start <lane> --kind claude --pane <pane> --timeout 120000

If user explicitly approved permission bypass at dispatch time:

    herdr agent start <lane> --kind claude --pane <pane> --timeout 120000 -- --dangerously-skip-permissions

- `--timeout 120000`: cold start buffer for Node/CLI initialization.

**Three disclosure lines §3 owes the user:**
- Approval posture: 默认安全审批模式（遇到权限请求需手动/规则确认）；仅在用户明确授权时使用 `--dangerously-skip-permissions`
- Drive mode: `单次提示驱动；无原生 goal 续跑，监督循环负责续跑`
- Rate limits: `所有 lane 共享 Claude 账号配额，可能触发速率限制`

**Verify readiness before sending prompt:**
Claude Code may display a directory trust prompt on fresh worktrees:

    herdr agent read <lane> --source visible

If visible text matches directory trust or safety confirmation:

    herdr agent send-keys <lane> enter

Re-read until composer / prompt input line is visible. Then send the initial prompt:

    herdr agent prompt <lane> "Read .dispatch/TASK.md in this directory and work through its plan and checklist. Keep .dispatch/progress.md updated after every item. Write .dispatch/DONE when everything is finished and verified, then run the notify-back command TASK.md gives you."

Record the lane as phase `implementing`. Start every lane before supervising any.

---

## §6a Probe one lane

Claude Code manages local session identity in project directories:

1. **Session identity**:
   Project sessions reside in `~/.claude/projects/-<sanitized-cwd>/<session-id>.jsonl`
   where `<sanitized-cwd>` replaces `/` with `-` (e.g. `/tmp/repo` → `-tmp-repo`).

   Find latest session JSONL:

       ls -t ~/.claude/projects/-$(echo "$PWD" | sed 's|^/||; s|/|-|g')/*.jsonl 2>/dev/null | head -1

   Or when specifying `--session-id <uuid>` at launch, the UUID is deterministically tracked.

2. **Native resume**:
   - In the worktree directory:
     `claude --continue` (resumes most recent conversation in cwd)
   - By session ID:
     `claude --resume <session-id>`

3. **Probe fields**:
   - `turn_state`: from `herdr agent get <lane>` `agent_status`:
     - `idle` → `complete`
     - `working` → `working`
     - `blocked` → `blocked`
   - `used_pct`: `null` (not exposed externally)
   - `mtime`: modification time of latest session JSONL or worktree activity
   - `goal_status`: `null`

---

## §6c Classify each lane, in this order

| Class | Test | Action |
| --- | --- | --- |
| `terminal` | phase is `verified` or `failed`, or user-paused | Skip |
| `done` | `.dispatch/DONE` exists **and** `turn_state == complete` | Verify (§6e — False DONE check); mark verified or reject |
| `blocked` | `agent_status == blocked` | Read `--source visible`, handle (§6g) |
| `stalled` | `state_change_seq` unchanged ≥ 15 min | Read `--source visible`; if prompt idle, treat as `idle_incomplete`; else escalate |
| `idle_incomplete` | `agent_status == idle`, no `.dispatch/DONE` | Read progress.md, send continuation prompt, record nudge; repeated nudges with no progress → escalate |
| `working` | otherwise (`agent_status == working`) | Leave alone |

---

## §6d Steer an idle or incomplete lane

When classified as `idle_incomplete`:
1. Read `.dispatch/progress.md` and check remaining unchecked items in `.dispatch/TASK.md`.
2. Send targeted continuation prompt:

       herdr agent prompt <lane> "Continue working through .dispatch/TASK.md. Update .dispatch/progress.md and write .dispatch/DONE when complete."

3. Record nudge count in state file. If 3 consecutive nudges produce no progress, pause lane and escalate.

---

## §6g Handle a blocked lane

When `agent_status == blocked` or Claude prompts on screen:
1. Read visible screen: `herdr agent read <lane> --source visible`
2. If benign operation within lane checkout (e.g., editing local file, running test command):
   Send approval: `herdr agent send-keys <lane> y` or `enter`
3. If operation leaves blast radius (network push, deleting outside files, sudo):
   Do NOT approve. Pause lane and escalate to user.

---

## §6h Compact or resume a lane

When context is full or performance degrades:
- Send `/compact` command to the lane:

      herdr agent prompt <lane> "/compact" --wait --until idle --timeout 120000

- If agent crashed or exited, resume session in the pane:

      herdr agent start <lane> --kind claude --pane <pane> --timeout 120000 -- --continue
