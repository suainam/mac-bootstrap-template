# Codex driver — §5a, §5c, §6a, §6c, §6d, §6g, §6h (OMP edition)

Adapted from upstream `bestony/herdr-dispatch` skills/dispatch-codex/references/driver.md.
OMP difference: lane_state.py lives at `~/.omp/dispatch-codex/bin/lane_state.py`.
Claims marked **(verified)** were checked against codex **0.151.0+**.

---

## §5a Pre-flight the pane

Run in the lane's pane (not via `command -v`):

    herdr pane run <pane> "codex --version"

Then poll `herdr pane read <pane> --source visible` (not `--source` alone; not `wait-output`).

- `codex` not found or version fails → stop that lane, report it. `agent start --kind codex`
  resolves from the pane's login shell; args cannot redirect it.
- Dependencies missing → run the repo's install command in the pane before `agent start`.
- `.env` / secrets missing → **ask the user** whether to symlink them. Never copy secrets.

Then write the brief (§5b in plan.md) before launching.

---

## §5c Launch Codex and set the goal

Launch with **no positional prompt** (goal is set by slash command after startup):

    herdr agent start <lane> --kind codex --pane <pane> --timeout 120000 -- \
      --no-alt-screen -c 'tui.status_line=["context-remaining"]'

- `--no-alt-screen`: inline output, readable scrollback via `agent read --source recent-unwrapped`.
- `-c 'tui.status_line=["context-remaining"]'`: forces `Context N% left` wording (a config that
  renders `Context N% used` causes `context left` grep to find nothing silently).
- `--timeout 120000`: cold start is 6–9 s; MCP boot can be much longer.
- **Never** pass `--full-auto` — removed in codex 0.151.0.
Default: retain configured approval/sandbox policy. Only when the user explicitly approved
`--yolo` for this run, append `--dangerously-bypass-approvals-and-sandbox` to the launch flags.
Worktree isolation is not a sandbox: the worker may still access the home directory.

**Three disclosure lines §3 owes the user (driver's wording):**
- Approval posture: `沿用当前 Codex 审批与沙箱配置` by default; with approved `--yolo`,
  `绕过审批与沙箱（工作树不是安全边界）`.
- Drive mode: `以 codex goal 模式运行（/goal 长任务）：跨 turn 自动续跑，中途暂停/限流由监督循环恢复`
- Rate limits: `所有 lane 共享一个 Codex 账号，速率窗口共享，可能同时限流`

**Verify readiness before sending the goal.** `agent start` returning `agent_status: idle` and
`interactive_ready: true` does NOT mean Codex is ready — fresh worktrees trigger a trust modal:

    herdr agent read <lane> --source visible

If a folder trust dialog appears, stop and ask the user to confirm that specific
disposable checkout. Never auto-confirm trust based solely on the planned lane.

Re-read until the `› Ask Codex to do anything` composer is visible. Then:

    herdr agent prompt <lane> "/goal Work through .dispatch/TASK.md in this directory: follow its plan in order, satisfy every acceptance criterion, keep .dispatch/progress.md updated after every checklist item, and finish by writing .dispatch/DONE and running the notify-back command TASK.md gives you."

Record phase `implementing`, launch time, the Herdr pane id and the Codex session UUID
only after matching its rollout metadata to this checkout (§6a).

On `/goal` error, fall back to one-shot prompt (same objective; record `goal_skipped`):

    herdr agent prompt <lane> "Read .dispatch/TASK.md in this directory and work through its checklist. Keep .dispatch/progress.md updated after every item. Write .dispatch/DONE when everything is finished and verified, then run the notify-back command TASK.md gives you."

Start every lane before supervising any.

---

## §6a Probe one lane — write the helper once

If `~/.omp/dispatch-codex/bin/lane_state.py` is absent, write it, then call:

    python3 ~/.omp/dispatch-codex/bin/lane_state.py <session-uuid>

Herdr 0.9.2 does not expose a Codex `agent_session` in `herdr agent get`. After the
first turn, find the rollout whose `session_meta.payload.cwd` resolves to the recorded
checkout and whose `session_meta.payload.timestamp` is after this lane's recorded launch.
If zero or multiple candidates match, surface an identity ambiguity; never pick the
newest unrelated Codex rollout. Record the UUID from the selected filename and verify
the same UUID and pane before each steering action. A restarted thread needs a new UUID.
Future Herdr versions may expose `agent_session.value`: use it only after checking
that its rollout belongs to the recorded checkout and launch.

Helper reads only the **tail** (~2 MB) and reports:
- `used_pct` — `last_token_usage.input_tokens / model_context_window × 100` (not `total_token_usage`)
- `turn_state` — `complete` when last of `task_started`/`task_complete`/`turn_aborted` is
  `task_complete`, else `working`
- `compactions` — count of top-level `{"type":"compacted"}` records
- `mtime` — rollout modification time
- `out_of_room` — whether tail contains Codex's `ran out of room` marker
- `goal_status`, `goal_tokens` — query `~/.codex/goals_1.sqlite`
  (`SELECT status, tokens_used FROM thread_goals WHERE thread_id = ?`)
  Status: `active`/`paused`/`blocked`/`usage_limited`/`budget_limited`/`complete`/null.
  **Use `~/.codex/goals_1.sqlite` (root), NOT `~/.codex/sqlite/goals_1.sqlite` (stays empty).**

---

## §6c Classify each lane, in this order

| Class | Test | Action |
| --- | --- | --- |
| `terminal` | phase is `published`, `failed`, user-paused, or `verified` with recorded §6f degrade reason | Skip |
| `unpublished` | phase `verified`, `push_attempts` < 3, no degrade reason, `pushed_sha` missing or behind branch HEAD, or `pr_url` missing with push enabled | Retry publish (§6f) |
| `done` | `.dispatch/DONE` exists **and** `turn_state == complete` | Verify (§6e), publish (§6f), mark terminal |
| `blocked` | `agent_status == blocked` | Read `--source visible`, handle (§6g) |
| `hard_fail` | `out_of_room` and no §6h restart in flight | Compact impossible; restart per §6h |
| `goal_parked` | `goal_status` is `paused`, `usage_limited`, or `budget_limited` | Resume or surface (§6d) |
| `goal_blocked` | `goal_status` is `blocked` | Steer or escalate (§6d) |
| `stalled` | `state_change_seq` **and** `mtime` both unchanged ≥ 15 min, and `goal_status` not `complete` | Read `--source visible` once; resolve if parked list/modal; `idle_incomplete` if composer idle; else escalate |
| `hot` | `used_pct ≥ 70` **and** `turn_state == complete` | Compact (§6h) |
| `idle_incomplete` | `done`/`idle`, no DONE file, `goal_status` not `active` | Read progress.md, send specific continuation prompt, record nudge; re-nudge with no progress → escalate |
| `working` | otherwise | Leave alone |

`unknown` `agent_status` is an anomaly to surface, never a completion.

---

## §6d Steer a goal lane

All slash commands via `herdr agent prompt <lane> "…"`. Subject to §6b's prompt guard.

**`paused`/`usage_limited`/`budget_limited` → resume or surface:**

    herdr agent prompt <lane> "/goal resume"

- `paused` with no user-pause record → escalate, do not resume; likely user's own hand.
- `paused` with user-pause record → terminal; resume only when user says so.
- `usage_limited` → resume once per sweep; if window still exhausted, next sweep retries.
- `budget_limited` → escalate once, resume only on user's word.

**`blocked` → steer or escalate.** Read `.dispatch/progress.md` and `--source visible`. If
inside §3-confirmed plan: send corrective prompt with `--wait --until idle --timeout 120000`,
then `/goal resume`. If real blocker outside plan scope: escalate with reason, do not improvise.

**`complete` but no DONE** → `idle_incomplete` path is safe (no active goal, no collision risk).

**`Replace goal?` list on screen** → answer with `send-keys` only:
`herdr agent send-keys <lane> 2` (cancels, keeps current goal). Fix the state file double-fire.

---

## §6g Handle a blocked lane

Under default yolo, no approval overlays; `blocked` = trust modal or herdr misclassification.
Under `--no-yolo`, overlays are real — read `--source visible` first.

Codex overlay titles: `Would you like to run the following command?` / `make the following edits?`
/ `grant these permissions?` / `send input to the existing terminal?`
Hotkeys: `y` approve, `a` approve-for-session, `p` approve-for-prefix, `d` deny, `c` cancel.

- Benign, inside lane's checkout (edit, run tests, read files) → `herdr agent send-keys <lane> y`
- Notify-back command exactly matching §5b template under `--no-yolo` → approve with `y`
- Anything leaving blast radius (push, pr create, force ops, sudo, external writes, credential reads)
  → **do not answer**; pause lane, record, surface to user

`herdr agent prompt` returns `agent_blocked` while dialog is up → clear with `send-keys` first.

---

## §6h Compact a lane

    herdr agent prompt <lane> "/compact" --wait --until idle --timeout 120000

If `out_of_room` (hard_fail): restart with a fresh Codex thread on the same pane, then re-prime:

1. Verify pane is at idle shell (§5a checks apply again)
2. `herdr agent start <lane> --kind codex --pane <pane> --timeout 120000 -- <same flags as §5c>`
3. Re-prime with the §5c `/goal` command (fresh thread has no goal — dialog-free)
4. Re-read the new session uuid from `herdr agent get <lane>` after first turn; re-record in state

On a `Replace goal?` list instead of the composer: `send-keys <lane> 2` (cancel), then re-inspect.
