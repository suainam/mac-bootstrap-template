# OMP driver — §5a, §5c, §6a, §6c, §6d, §6g, §6h (OMP edition)

Adapted for OMP worker agents running under Herdr (`dispatch-omp`).

> **Pi worker status**: Pi worker is NOT implemented in this driver because `pi` CLI is absent on
> this workstation (`pi: command not found`). Per #115 / #109 spec, Pi worker dispatch cannot be completed
> until `pi` CLI is installed and available; this limitation is reported as an active blocker for #115.

---

## §5a Pre-flight the pane

Run in the lane's pane (not via `command -v`):

    herdr pane run <pane> "omp --version"

Then poll `herdr pane read <pane> --source visible` (not `--source` alone; not `wait-output`).

- `omp` not found or version fails → stop that lane, report it. `agent start --kind omp`
  resolves from the pane's login shell; args cannot redirect it.
- Dependencies missing → run the repo's install command in the pane before `agent start`.
- `.env` / secrets missing → **ask the user** whether to symlink them. Never copy secrets.

Then write the brief (§5b in plan.md) before launching.

---

## §5c Launch OMP agent and set prompt

Launch OMP worker in the lane pane with isolated session directory:

    herdr agent start <lane> --kind omp --pane <pane> --timeout 120000 -- \
      --session-dir ~/.omp/dispatch-omp/<run-id>/sessions/<lane>/

Key flags & configuration:
- `--session-dir ~/.omp/dispatch-omp/<run-id>/sessions/<lane>/`: isolates session storage per lane,
  while keeping the host's credentials, `models.yml`, `config.yml`, and `.env` intact from `~/.omp/agent/`.
- **Do NOT pass `--no-session`**: `--no-session` prevents saving session history and contradicts the
  required native `--resume` capability.
- **Do NOT pass `--profile worker-<lane>`**: isolated profiles create a bare `~/.omp/profiles/<name>/agent/`
  directory lacking the configured models, providers, and environment secrets.
- **Approval posture**: default is safe manual approval. Do NOT pass `--auto-approve` or `--approval-mode=yolo`
  unless the user explicitly granted approval bypass at dispatch time. Under default safe mode, §6g handles
  benign approval prompts in the lane.
- `--timeout 120000`: cold start allowance.

**Three disclosure lines §3 owes the user (driver's wording):**
- Approval posture: `默认安全审批（safe manual approval，文件/终端操作由监督逻辑协助确认）；仅在明确授权时放行 yolo`
- Drive mode: `单次提示驱动（OMP worker 模型交互）；监督循环负责续跑与状态恢复`
- Rate limits: `所有 lane 共享宿主环境配置的 API 提供商配额与并发限制`
**Verify readiness before sending the task prompt:**

    herdr agent read <lane> --source visible

Poll until the OMP prompt / composer is visible (e.g. `>` prompt or input indicator).

Then send the initial instruction:

    herdr agent prompt <lane> "Read .dispatch/TASK.md in this directory and work through its checklist in order. Keep .dispatch/progress.md updated after every item. Write .dispatch/DONE when everything is finished and verified, then run the notify-back command TASK.md gives you."

Record the lane as phase `implementing` with its lane identifier and timestamp.

Start every lane before supervising any.

---

## §6a Probe one lane

For an OMP lane:
1. Query Herdr agent status:

       herdr agent get <lane>

   Inspect `result.agent.agent_status` (`idle`, `busy`, `blocked`, `exited`).
2. Turn state and session inspection:
   OMP session files are written in the lane's `--session-dir`:

       ls -t ~/.omp/dispatch-omp/<run-id>/sessions/<lane>/*.jsonl 2>/dev/null | head -1

   Extract `<session-id>` from filename (`<timestamp>_<uuid>.jsonl`).
   Inspect mtime of the file.
3. Tail probe:
   Read last records of the session file to check for last assistant message, error events, or token usage.
   - `turn_state`: `complete` when agent status is `idle` and no pending tool calls; `working` when busy.
   - `goal_status`: `null` (OMP has no goal sqlite subsystem).
   - `mtime`: timestamp of newest session update.

---

## §6c Classify each lane, in this order

| Class | Test | Action |
| --- | --- | --- |
| `terminal` | phase is `published`, `failed`, user-paused, or `verified` with recorded §6f degrade reason | Skip |
| `unpublished` | phase `verified`, `push_attempts` < 3, no degrade reason, `pushed_sha` missing or behind branch HEAD, or `pr_url` missing with push enabled | Retry publish (§6f) |
| `done` | `.dispatch/DONE` exists **and** `turn_state == complete` | Verify (§6e), publish (§6f), mark terminal |
| `blocked` | `agent_status == blocked` | Read `--source visible`, handle (§6g) |
| `stalled` | `state_change_seq` **and** `mtime` both unchanged ≥ 15 min | Read `--source visible` once; nudge if idle; else escalate |
| `idle_incomplete` | `agent_status == idle`, no DONE file | Read progress.md, send specific continuation prompt, record nudge; re-nudge with no progress → escalate |
| `working` | otherwise | Leave alone |

`unknown` `agent_status` is an anomaly to surface, never a completion.

---

## §6d Steer an OMP lane

When an OMP lane stops before writing `.dispatch/DONE`:

1. Read `.dispatch/progress.md` and `herdr agent read <lane> --source visible`.
2. If the lane is idle with checklist items remaining, send a continuation prompt:

       herdr agent prompt <lane> "Continue with the remaining items in .dispatch/TASK.md. Update .dispatch/progress.md after each step. Write .dispatch/DONE when complete."

3. If the lane encounters an error or requires clarification within the planned scope, provide steering advice via prompt.
4. If a blocker lies outside the planned scope, escalate to user.

---

## §6g Handle a blocked lane

Under default safe approval mode, OMP may pause for confirmation before file writes or tool executions.
Additionally, directory trust dialogs or CLI confirmation prompts may appear in the terminal.

Resolution:
1. Read `herdr agent read <lane> --source visible`.
2. Check the waiting confirmation prompt:
   - Benign operations within the lane's worktree (file edits, test commands, reads): send
     `herdr agent send-keys <lane> y` (or `enter`).
   - Operations outside the lane worktree (network push, deleting files outside worktree, secret reads):
     **do not approve**; pause lane and escalate to user.
3. If an API key or external service is blocked: escalate to user.
---

## §6h Compact or restart an OMP lane

OMP does not provide an in-session `/compact` slash command.
If a worker process becomes unresponsive or exits unexpectedly:

1. Verify pane is at idle shell.
2. Native resume from previous session state:

       herdr agent start <lane> --kind omp --pane <pane> --timeout 120000 -- \
         --session-dir ~/.omp/dispatch-omp/<run-id>/sessions/<lane>/ --resume <session-id>

   where `<session-id>` is the session UUID identified from the session JSONL filename in §6a.
   Alternatively, pass `-c` / `--continue` to continue the latest session in that directory.
3. If fresh restart is needed:

       herdr agent start <lane> --kind omp --pane <pane> --timeout 120000 -- \
         --session-dir ~/.omp/dispatch-omp/<run-id>/sessions/<lane>/

4. Re-send prompt to continue from `.dispatch/progress.md`.
