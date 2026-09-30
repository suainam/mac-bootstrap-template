# Supervision — §6b, §6e–§6f, §6i, §7, §8 (OMP edition)

Adapted from upstream `bestony/herdr-dispatch` skills/_shared/supervise.md.
OMP differences:
- State dir: `~/.omp/<skill-name>/`
- Loop: OMP loop mode (`--loop`) + `--resume`; no external `loop` skill
- Publish: default **no-push, no-PR**; §6f only runs when `--push` was passed

The probe contract is identical to upstream; refer to driver.md §6a.

---

## §6b Poll the whole fleet in one call

`herdr agent list` returns every lane's `agent_status` and `state_change_seq`. Do not read panes
during a normal sweep.

**Verify identity before steering any lane.** Confirm session id from
`herdr agent get <lane> | jq -r '.result.agent.agent_session.value'` matches the recorded one.
On mismatch, diagnose:
- Name resolves in another workspace → stranger re-claimed it; surface, never touch.
- Same pane, different id → restart in flight or user's hand; check state file, surface if unclear.
- Name resolves to nothing → agent exited; relaunch per driver §5c on recorded pane when idle.

**Prompt guard.** Before any input this sweep sends a lane, read once:

    herdr agent read <lane> --source visible

If a selection list or modal is parked, resolve it first (§6d/§6g); never send a prompt to a
parked pane.

---

## §6e Verify a finished lane

Re-run everything yourself — the lane's DONE claim is what you are checking, not what you accept.

    git -C <checkout> status --porcelain              # must be empty
    git -C <checkout> log --oneline <base>..<branch>  # must be non-empty

Then execute each §3-confirmed acceptance criterion command from the lane's checkout and require
its expected outcome. Judge non-mechanical criteria from the diff and `.dispatch/progress.md`.
Read `progress.md` to confirm every checklist item is ticked and surface any recorded deviation.

A deviation is not a failure — judge on merits — but it must surface in §8, never silently.

Commit granularity: compare commit count to checklist length. A coarse commit is a §8 report line,
not a gate; never ask the agent to rewrite history.

Only a lane passing **every** criterion becomes phase `verified`.

---

## §6f Publish a verified lane (only when `--push` was passed)

**Default posture: no push, no PR.** If `--push` was not in the run's recorded flags, set phase
`verified_local`, print the manual push command for the user, and stop here:

    git -C <checkout> push -u origin refs/heads/<branch>:refs/heads/<branch>

When `--push` was passed, proceed:

**1. Preconditions (degrade with recorded reason):**
- No `origin` → leave `verified`, report local-only
- `gh` missing / unauthenticated, or `--no-pr` → push only; print `gh pr create` command
- PR base not on origin → push only; print command with base left for user

**2. Push exactly one branch:**

    git -C <checkout> push -u origin refs/heads/<branch>:refs/heads/<branch>

Never `--all`, `--force`, `--force-with-lease`, never the base branch. Rejected non-fast-forward
→ stop, record, surface; do not force.

**3. Reuse existing PR before creating:**

    gh pr list --repo <owner/repo> --head <branch> --state all --json number,url,state

Non-empty → record and stop.

**4. Create PR:**

    gh pr create --repo <owner/repo> --base <pr-base> --head <branch> \
      --title '<conventional-commit title>' \
      --body-file ~/.omp/<skill-name>/<run-id>/<lane>-pr.md

Body (English): checklist final state; `Closes #<issue>` if applicable; summary from progress.md
(file is git-excluded — carry content over, do not link); acceptance criteria with verified
outcomes; any plan deviation; provenance line naming run id, lane, and that an agent wrote the code
while the orchestrator verified before push. Do not name the model or approval posture.

**5. Close lane.** Record `pr_url`, set phase `published`. On failure, record stderr, bump
`push_attempts`; after 3 failures stop, record degrade reason (`verified_push_failed`), surface
with exact command for user to run.

---

## §6i Close the sweep

Rewrite state file atomically (write `.tmp`, `mv`). Emit **one line per lane**:
lane | phase | goal_status | used_pct | compactions | turn_state | PR or `—`

Escalation outcomes recorded on first occurrence; later sweeps re-surface as one line, never
re-escalate.

---

## §7 Arm the recurring loop

Unless `--no-loop` was in the run's recorded flags:

Tell the user in Chinese that supervision will continue. In OMP, the loop relies on OMP's own
**loop mode** (`/loop` or equivalent) combined with this skill's `--resume` flag, OR the user
manually re-invoking `/dispatch-codex --resume` each turn.

- If OMP loop mode is active in this session: the session will sweep on each turn automatically.
- If OMP loop mode is not active: tell the user in Chinese to re-invoke `/dispatch-codex --resume`
  to run a supervision sweep, or enable loop mode.

A `--resume` sweep re-arms the loop (unless `--no-loop` recorded) and re-records
`orchestrator_pane` as the current pane — that is how a run whose original session died gets its
supervision back.

**The less autonomous the agent, the more the sweep is the engine.** Codex goal mode auto-continues,
so the sweep is a repair path. Under `--no-yolo` with overlays, sweeps are slower.

Stop the loop when every lane is terminal or awaiting-user. Tell the user which lanes wait on what.

Terminal = `published` / `failed` / user-paused / `verified_local` / `verified_push_failed`.
Awaiting-user = a recorded `escalated` not yet answered.

A `verified_local` lane (--push not passed) is terminal — it is done, waiting for the user to push
by hand if they choose to.

---

## §8 Report

Per lane (in Chinese):
- 分支, checkout 路径, 状态
- 已完成/剩余清单项
- commit 数（粒度过粗时标注）
- **验收标准逐条结果**（通过/未通过/无法机械验证时给依据）
- agent 运行情况（goal_status, token用量, 有无暂停/限流/阻塞经历, 降级原因）
- 是否偏离已确认实施计划（有则一句话说明）
- compaction 次数
- **推送状态**：已推送+PR链接 / 待用户手动推送（命令如下） / 推送失败（命令如下）

Name the agent and version once at the top. Say plainly: you did **not** push unless `--push` was
passed and verification succeeded. You did **not** merge. You did **not** remove any workspace.

Print (do not run) follow-up commands in this order:

    # 1. Only after you are done reviewing the worktree:
    herdr worktree remove --workspace <ws>             # destroys checkout AND kills agent process

    # 2. (If --push was passed and PR was opened:)
    gh pr merge <pr-number> --squash --delete-branch   # after your own review

    # 3. (If branch outlived the PR merge:)
    git -C <repo> branch -d <branch>

`worktree remove` runs before `gh pr merge` — git refuses to delete a branch checked out in a
worktree; merge would report partial success. Warn that `worktree remove` discards uncommitted
work and each lane may have TWO workspace ids (§4).

When `--push` was not passed, the push/PR commands belong to the user's own choice:

    git -C <checkout> push -u origin refs/heads/<branch>:refs/heads/<branch>
    gh pr create --repo <owner/repo> --base <pr-base> --head <branch> \
      --title '…' --body '…'
