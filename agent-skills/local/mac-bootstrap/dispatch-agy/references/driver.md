# agy (Antigravity CLI) driver — §5a, §5c, §6a, §6c, §6d, §6g, §6h (OMP edition)

Adapted for agy (Antigravity CLI) running under Herdr.
- **Herdr Integration**: `antigravity-cli` (installed via `herdr integration install antigravity-cli`). Wires into `~/.gemini/config/hooks/herdr-agent-state.sh`, which automatically reports native session identity (`conversationId`, `transcriptPath`) to Herdr via `pane.report_agent_session`.
- **Herdr Agent Kind**: `--kind agy` (the CLI binary name is `agy`, canonical herdr kind is `agy`).
- **Execution Model**: Nudge-driven; prompt turns driven by supervisor, with safe default approval handling and native resume.
- **No Publication**: By default, no remote push, no PR creation. Work remains in the local worktree branch.

---

## §5a Pre-flight the pane

1. Verify the Herdr integration is installed:
   ```bash
   herdr integration status | grep -E "^antigravity-cli:"
   ```
   If missing or not installed, run:
   ```bash
   herdr integration install antigravity-cli
   ```
2. Run in the lane's pane (not via `command -v`):
   ```bash
   herdr pane run <pane> "agy --version"
   ```
   Then poll `herdr pane read <pane> --source visible` (not `--source` alone; not `wait-output`).

- `agy` not found or version fails → stop that lane, report it. `agent start --kind agy`
  resolves from the pane's login shell; args cannot redirect it.
  *Note:* herdr kind is `agy`; integration name is `antigravity-cli`.
- Dependencies missing → run the repo's install command in the pane before `agent start`.
- `.env` / secrets missing → **ask the user** whether to symlink them. Never copy secrets.

Then write the brief (§5b in plan.md) before launching.

---

## §5c Launch agy and set initial prompt

Launch with safe default posture (manual approval handling). Only pass `--dangerously-skip-permissions` if the user explicitly provided `--yolo`:

    # Safe default:
    herdr agent start <lane> --kind agy --pane <pane> --timeout 120000

    # With explicit user approval (--yolo):
    herdr agent start <lane> --kind agy --pane <pane> --timeout 120000 -- --dangerously-skip-permissions

- `--timeout 120000`: wait up to 120s for interactive readiness.

**Three disclosure lines §3 owes the user (driver's wording):**
- Approval posture: `默认安全审批（工具权限请求由监督循环按需审批）` or `--yolo（已显式绕过权限检查：--dangerously-skip-permissions）`
- Drive mode: `单次提示驱动；监督循环负责续跑、审批与状态推进`
- Rate limits: `所有 lane 共享同一个 agy 账号，速率窗口共享，可能同时限流`

**Verify readiness before sending prompt.** Check for interactive composer:

    herdr agent read <lane> --source visible

Wait until the interactive input prompt is visible. Then prime with the initial task instructions:

    herdr agent prompt <lane> "Read .dispatch/TASK.md in this directory and work through its checklist in order. Keep .dispatch/progress.md updated after every item. Satisfy every acceptance criterion. When all tasks and criteria are met and git status is clean, write .dispatch/DONE and run the notify-back command TASK.md gives you."

Record the lane as phase `implementing` with its native session id once reported.

Start every lane before supervising any.

---

## §6a Probe one lane

Probe state from herdr status and the lane's workspace:

1. **Native Session Identity:**
   Extracted from herdr agent session metadata reported by the `antigravity-cli` lifecycle hook:
   ```bash
   herdr agent get <lane> | jq -r '.result.agent.agent_session.value // .result.agent.agent_session_id // empty'
   ```
   Do NOT run guessed CLI commands (e.g. `agy session list` does not exist).
2. **Turn state (Settled vs Working):**
   Derived from herdr `agent_status`:
   - `idle` → `complete` / settled (turn finished, awaiting next input or done)
   - `working` → `working`
   - `blocked` → `blocked`
3. **Used percent:** `null` (agy does not emit context window percentage to rollout files).
4. **Mtime:** Check mtime of active configuration or cache directories (e.g. `~/.gemini/` or `~/.config/agy/`).
5. **Goal status:** `null` (agy does not use Codex goals).

---

## §6c Classify each lane, in this order

| Class | Test | Action |
| --- | --- | --- |
| `terminal` | phase is `published`, `failed`, user-paused, or `verified` with recorded §6f degrade reason | Skip |
| `done` | `.dispatch/DONE` exists **and** `turn_state == complete` | Verify (§6e); on failure handle as false DONE (§6e); on success mark verified |
| `blocked` | `agent_status == blocked` | Read `--source visible`, handle approval or prompt (§6g) |
| `stalled` | `state_change_seq` **and** `mtime` both unchanged ≥ 15 min | Read `--source visible` once; resolve if modal; `idle_incomplete` if composer idle; else escalate |
| `idle_incomplete` | `agent_status == idle`, no DONE file | Read `.dispatch/progress.md`, send specific continuation prompt, record nudge; re-nudge with no progress → escalate |
| `working` | `agent_status == working` | Leave alone |

`unknown` `agent_status` is an anomaly to surface, never a completion.

---

## §6d Steer an agy lane

When a lane is `idle_incomplete`:
1. Read `.dispatch/progress.md` and `git -C <checkout> status --porcelain`.
2. Send a specific continuation nudge:
   ```bash
   herdr agent prompt <lane> "Continue working through .dispatch/TASK.md. Check off finished items in .dispatch/progress.md. If finished and verified, write .dispatch/DONE and run the completion notify-back."
   ```
3. Record nudge count. If 3 consecutive nudges result in no commits or progress changes, escalate to user.

---

## §6e False DONE detection and verification

When `.dispatch/DONE` exists:
The supervisor does NOT trust the lane's DONE claim. Re-run the EXACT user-approved acceptance criteria from `.dispatch/TASK.md`:
1. Run `git -C <checkout> status --porcelain` (must be clean).
2. Execute the exact acceptance command specified in the brief.
3. **If the acceptance check fails (False DONE):**
   - Do NOT mark lane `verified`.
   - Lane stays in `implementing` / `false_done`.
   - Send corrective prompt with the EXACT failure output:
     ```bash
     herdr agent prompt <lane> "Acceptance criterion failed: <cmd> returned non-zero exit code. Error: <stderr>. Please fix the implementation so that the acceptance check passes, then re-write .dispatch/DONE."
     ```
4. **If and only if ALL criteria pass**, mark phase `verified` (or `verified_local`).

---

## §6g Handle a blocked lane (Settled / Blocked State)

When `agent_status == blocked`:
1. Inspect the terminal screen:
   ```bash
   herdr agent read <lane> --source visible
   ```
2. **Safe Manual Approval Policy:**
   - Benign operations strictly inside the lane's isolated worktree checkout (e.g. file edits, running test commands, reading files): approve by sending keys:
     ```bash
     herdr agent send-keys <lane> y
     # or enter if an acknowledgement prompt:
     herdr agent send-keys <lane> enter
     ```
   - Anything touching the host, leaving the worktree blast radius (network pushes, global writes, secrets access, sudo): **never auto-approve**; pause the lane and surface to the user for decision.
3. If prompt previously returned `agent_blocked`, clear with `send-keys` before issuing new prompts.

---

## §6h Native resume and session recovery

When an agy session in a pane terminates, crashes, or needs restart:
1. Native resume using the captured session identity (`conversationId`):
   ```bash
   herdr agent start <lane> --kind agy --pane <pane> --timeout 120000 -- --conversation <conversation_id>
   ```
2. Or native resume of the most recent conversation in the worktree:
   ```bash
   herdr agent start <lane> --kind agy --pane <pane> --timeout 120000 -- --continue
   ```
   (Only append `--dangerously-skip-permissions` if `--yolo` was explicitly approved by user).
3. Re-prime with the continuation prompt (§6d) to resume work.
