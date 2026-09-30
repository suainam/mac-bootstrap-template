# Supervision — §6b, §6e, §6i, §7, §8 (OMP edition)

Adapted from upstream `bestony/herdr-dispatch` skills/_shared/supervise.md.
OMP differences:
- State dir: `~/.omp/<skill-name>/` (e.g. `~/.omp/dispatch-claude/`)
- Loop: OMP loop mode (`--loop`) + `--resume`
- Local verification only: **no push, no PR**

---

## §6b Poll the whole fleet in one call

`herdr agent list` returns every lane's `agent_status` and `state_change_seq`. Do not read panes
during a normal sweep.

**Verify identity before steering any lane.** Confirm lane exists and pane resolves.
On mismatch, diagnose:
- Name resolves in another workspace → stranger re-claimed it; surface, never touch.
- Same pane, different session → restart in flight or user's hand; check state file, surface if unclear.
- Name resolves to nothing → agent exited; relaunch per driver §5c on recorded pane when idle.

**Prompt guard.** Before any input this sweep sends a lane, read once:

    herdr agent read <lane> --source visible

If a selection list, dialog, or trust modal is parked, resolve it first (§6g); never send a prompt
to a parked pane.

---

## §6e Verify a finished lane (False DONE check)

Re-run everything yourself — the lane's DONE claim is what you are checking, not what you accept.

**Critical: False DONE check must use the exact SAME user-approved acceptance criterion
specified in the lane's brief (`TASK.md`).**

1. Basic git checks:
       git -C <checkout> status --porcelain              # must be clean

2. Independent execution of the brief's acceptance criteria:
   Execute the exact acceptance commands agreed in §3 / written in `.dispatch/TASK.md`.
   - If ANY acceptance criterion fails:
     - **REJECT the DONE claim**: The lane is NOT finished.
     - Record rejection reason and failed command output in `state.json`.
     - Remove or disregard `.dispatch/DONE`.
     - Set lane status back to `implementing` / `idle_incomplete`.
     - Send corrective prompt to the lane:
       `herdr agent prompt <lane> "Acceptance criterion failed: <command> failed with: <error>. Fix the implementation and re-verify before writing .dispatch/DONE."`
     - Do NOT mark lane as verified.
   - If ALL acceptance criteria pass:
     - Lane transitions to `verified`.
     - Record verification evidence in `state.json`.

---

## §6i Sweep output

At the end of every supervision sweep, print a concise table in Chinese summarizing lane states:

| Lane | Phase | Agent Status | Turn State | Details / Next Action |
| --- | --- | --- | --- | --- |

Rewrite state file atomically:
`write ~/.omp/dispatch-claude/<run-id>/state.json.tmp` then `mv`.

---

## §7 Recurring supervision loop

If `--no-loop` was not passed and there are non-terminal lanes remaining, arm the loop for the next
sweep interval (e.g. 30–60s) using OMP loop mode with `dispatch-claude --resume`.

When all lanes reach terminal phases (`verified`, `failed`), exit loop.

---

## §8 Final report

When all lanes finish, print the final completion report:
- Overview of all lanes (status, branch, commit hashes)
- Verification evidence for each lane (executed acceptance criteria outputs)
- Any false DONE rejections or deviations recorded
- Note that changes remain in local worktrees (no remote publication)
