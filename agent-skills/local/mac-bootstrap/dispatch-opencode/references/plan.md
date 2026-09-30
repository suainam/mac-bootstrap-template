# Dispatch — §2 to §5b (agent-independent, OMP edition)

Adapted from upstream `bestony/herdr-dispatch` skills/_shared/plan.md for OMP.
Key differences: state dir is `~/.omp/<skill-name>/`, `ask` replaces `AskUserQuestion`,
push/PR requires explicit `--push` flag (default is no-push, no-PR).

---

## §2 Repo, run id, state file

Resolve `git rev-parse --show-toplevel`. Empty → stop, tell user in Chinese this requires a git
repo. If `git rev-parse --git-dir` and `--git-common-dir` differ, you are in a linked worktree;
stop and ask user to re-run from the main checkout.

Prefer current branch / HEAD as base ref. Do not fetch from origin without explicit user
authorization or verified network need. With no remote, use local branch and say so.

Run id: six lowercase alphanumerics from `date +%s | tail -c 7 | head -c 6`. State dir
`~/.omp/<skill-name>/<run-id>/` — `<skill-name>` is this skill's own name (`dispatch-opencode`).
`mkdir -p` it. If another run dir for this repo still holds non-terminal lanes, ask the user
(via `ask`) whether to resume, archive, or abort — do not start a second run silently.

Record in the state file before anything is created: `skill`, `agent_kind` (`opencode`), `flags`,
`repo`, `base`, `orchestrator_pane` (from `$HERDR_PANE_ID`).

**Publishing preflight.** Check only (do not install or authenticate anything):
- `origin` exists: `git -C <repo> remote get-url origin`
- `gh` auth: `gh auth status 2>/dev/null`
- `gh` repo: `gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null`
- PR base on origin: `git -C <repo> ls-remote --exit-code --heads origin <pr-base>`

Record each result. None failing is a reason to abort — they only determine what §6f can do.
**If `--push` was not passed, skip the `gh` check entirely — no PR will be opened.**

**Agent preflight.** Run `opencode --version` in the pane once (see driver §5a). Record the
version string.

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

1. **Agent and approval posture** — 默认安全模式（手动审批权限）；若显式传入 `--auto` 或 `--yolo` 则自动批准权限请求。
2. **How each lane is driven** — 单次提示+循环续跑（无 goal 模式）：每轮需要监督循环主动续跑。
3. **What happens when a lane finishes** — 默认：`验证通过后分支留在本地，不 push，不开 PR。传 --push 才会 push 到 origin（gh 已登录时自动开 PR）。`

Use `ask` to confirm: 按此派发 / 计划或验收标准要改 / 合并成更少的 lane / 我来调整.
**Create nothing before the user answers.** If changes requested, rework and ask again.

---

## §4 One workspace per lane (via Herdr worktree create)

Use `herdr worktree create` to create an isolated linked git worktree:

    herdr worktree create --cwd <repo> --branch <branch> --base <base> --label <lane> --no-focus

Extract from the JSON result:
- `workspace_id`: from `result.workspace.workspace_id`
- `pane_id`: from `result.root_pane.pane_id`
- `checkout_path`: from `result.worktree.path`

On name/label/path collision, append run-id tail and retry once. Any other failure → record lane as
`failed`, continue with the rest, report at end. Append each lane to the state file as it is created.

---

## §5b Write the brief into the lane's own checkout

Write between §5a (pre-flight) and §5c (launch). File: `<checkout>/.dispatch/TASK.md`.

    mkdir -p <checkout>/.dispatch
    exclude_file="$(git -C <checkout> rev-parse --git-path info/exclude)"
    mkdir -p "$(dirname "$exclude_file")"
    printf '.dispatch/\n' >> "$exclude_file"
- **Objective**
- **Plan** — the §3-confirmed plan verbatim; instruction to record deviations in progress.md
- **Checklist** as `- [ ]` items
- **Acceptance criteria** — the §3-confirmed criteria verbatim; DONE written only when all hold
- **Boundaries**: work only in this checkout; never cd to main checkout; never touch another
  lane's files; **never push, never merge, never open a PR**
- **Progress protocol** (quote verbatim):

> **Progress protocol.** Keep `.dispatch/progress.md` current after each checklist item: rewrite
> it with checklist tick state, what you just did, what you are about to do, and any decision a
> fresh reader needs. When every checklist item is done, every acceptance criterion holds, and
> changes are verified, write `.dispatch/DONE` with a one-line summary.

- **Notify-back** (substitute `<orch-pane>`, `<run-id>`, `<lane>`, `<skill>` literally):

> **Completion notify-back.** Immediately after writing `.dispatch/DONE`, run this exact command
> once:
>
>     herdr agent prompt <orch-pane> "[<skill> <run-id>] lane <lane> wrote DONE — run one <skill> --resume sweep now."
>
> If it errors, do not retry — the orchestrator polls on a timer regardless. This is the only
> herdr command in your job; never read, prompt, or send keys to any other pane or agent.

---

Now launch: driver §5c. Start every lane before supervising any, then read
`references/supervise.md` and continue at §6.
