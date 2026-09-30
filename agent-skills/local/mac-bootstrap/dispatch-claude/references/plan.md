# Dispatch — §2 to §5b (agent-independent, OMP edition)

Adapted from upstream `bestony/herdr-dispatch` skills/_shared/plan.md for OMP.
Key differences: state dir is `~/.omp/<skill-name>/`, `ask` replaces `AskUserQuestion`,
no automatic remote publishing (no push, no PR).

---

## §2 Repo, run id, state file

Resolve `git rev-parse --show-toplevel`. Empty → stop, tell user in Chinese this requires a git
repo. If `git rev-parse --git-dir` and `--git-common-dir` differ, you are in a linked worktree;
stop and ask user to re-run from the main checkout.

Use current branch or user-specified base. Avoid network calls (`git fetch origin`) unless
explicitly requested by the user.

Run id: six lowercase alphanumerics from `date +%s | tail -c 7 | head -c 6`. State dir
`~/.omp/<skill-name>/<run-id>/` — `<skill-name>` is this skill's own name (`dispatch-claude`).
`mkdir -p` it. If another run dir for this repo still holds non-terminal lanes, ask the user
(via `ask`) whether to resume, archive, or abort — do not start a second run silently.

Record in the state file before anything is created: `skill`, `agent_kind` (`claude`), `flags`,
`repo`, `base`, `orchestrator_pane` (from `$HERDR_PANE_ID`).

**Agent preflight.** Run `claude --version` once (see driver §5a). Record the version string.

---

## §3 Plan the lanes

Split task text on numbered items, newlines, or `;`. Then group: same lane when tasks touch the
same files, depend on each other, or would be reviewed together. Different lanes only when they can
run concurrently without editing the same files. Never exceed `--lanes N` (default 16).

Per lane derive `slug`, `name`, `type`, `issue`, `branch`, `tasks`, `plan`, `acceptance` — same
rules as upstream plan.md §3. Ground every `plan` step in the actual repo (Glob/Grep/Read the
code it names). Write `acceptance` as checkable commands using the repo's own test/lint/make
targets; never invent commands.

Present in Chinese: lane table (lane / 分支 / 包含的任务), then under each lane its 实施计划
(ordered steps) and 验收标准 bullets. Then **three disclosure lines**:

1. **Agent and approval posture** — safe approval posture by default (prompts for permissions); bypass requires explicit user approval.
2. **How each lane is driven** — Claude Code 单次提示驱动；无原生 goal 续跑，监督循环负责续跑.
3. **What happens when a lane finishes** — 验证通过后分支保留在本地 worktree，不自动 push 到远程，不开 PR。

Use `ask` to confirm: 按此派发 / 计划或验收标准要改 / 合并成更少的 lane / 我来调整.
**Create nothing before the user answers.** If changes requested, rework and ask again.

---

## §4 One worktree per lane

Create isolated git worktree via Herdr:

    herdr worktree create --cwd <repo> --branch <branch> --base <base> --label <lane> --no-focus

Extract from JSON response:
- `result.root_pane.pane_id`
- `result.root_pane.cwd` (worktree directory)
- `result.root_pane.workspace_id`

On collision or failure, report and record lane as `failed`. Append each lane to the state file
as it is created.

---

## §5b Write the brief into the lane's own checkout

Write between §5a (pre-flight) and §5c (launch). File: `<checkout>/.dispatch/TASK.md`.

    mkdir -p <checkout>/.dispatch
    EXCLUDE=$(git -C <checkout> rev-parse --git-path info/exclude)
    mkdir -p "$(dirname "$EXCLUDE")"
    printf '.dispatch/\n' >> "$EXCLUDE"

Brief contents (in English):
- **Objective**
- **Plan** — the §3-confirmed plan verbatim; instruction to record deviations in progress.md
- **Checklist** as `- [ ]` items
- **Acceptance criteria** — the §3-confirmed criteria verbatim; DONE written only when all hold
- **Boundaries**: work only in this checkout; never cd to main checkout; never touch another
  lane's files; **never push, never merge, never open a PR**
- **Commit policy**: Commit logically when changes are verified.
- **Progress protocol**:
  Keep `.dispatch/progress.md` current after each checklist item. When every checklist item is done,
  every acceptance criterion holds, and git status is clean, write `.dispatch/DONE` with a one-line summary.
- **Notify-back** (substitute `<orch-pane>`, `<run-id>`, `<lane>`, `<skill>` literally):

> **Completion notify-back.** Immediately after writing `.dispatch/DONE`, run this exact command once:
>
>     herdr agent prompt <orch-pane> "[<skill> <run-id>] lane <lane> wrote DONE — run one <skill> --resume sweep now."

---

Now launch: driver §5c. Start every lane before supervising any, then read
`references/supervise.md` and continue at §6.
