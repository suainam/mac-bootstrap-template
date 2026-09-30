---
name: dispatch-opencode
description: From an OMP session inside a Herdr pane, dispatch one or more tasks to OpenCode agents running in isolated git worktrees — plan, supervise, nudge-drive, and independently verify each lane to completion without touching the user's checkout or pushing to remote. Use when the user asks to dispatch/fan out/派发 tasks to OpenCode via Herdr lanes, or to resume supervision of an existing run (`--resume`). Fails clearly outside a Herdr pane.
argument-hint: '<task-1>; <task-2>; … [--lanes N] [--base <ref>] [--auto] [--no-loop] [--push] [--resume]'
---

# Dispatch tasks to OpenCode agents running under Herdr — OMP edition

The **raw request** is the text passed to this skill — its arguments, or when invoked with none,
the task text in the user's own message.

You are an **orchestrator**. You do not implement the tasks yourself. You split the request into
lanes, give each lane its own Herdr workspace and its own OpenCode agent, independently verify the
result, and report. **The lane's DONE claim never grants completion — you re-run the agreed checks
yourself (§6e).**

OpenCode has no `/goal` mode; it is **nudge-driven**. The supervision loop actively monitors each
lane and sends continuation prompts until completion.

This skill is derived from upstream `bestony/herdr-dispatch` skills/_shared and dispatch-codex,
adapted for OMP and OpenCode: state lives under `~/.omp/dispatch-opencode/`, `ask` replaces
`AskUserQuestion`, OMP's own loop mode replaces the upstream `loop` skill, and **push/PR is disabled
by default** (pass `--push` to enable after parent verification). Safe manual approval is the default
posture (pass `--auto` or `--yolo` for explicit bypass).

## How to read this skill

Section numbers (§0–§8) are continuous across all four files:

| Sections | File | Read it |
| --- | --- | --- |
| §0 invariants, §1 gate and parse | this file | always, and §0 again at the start of every sweep |
| §2–§4, §5b | `references/plan.md` | fresh dispatch only, before creating anything |
| §5a, §5c, §6a, §6c, §6d, §6g, §6h | `references/driver.md` | everything OpenCode-specific |
| §6b, §6e, §6f, §6i, §7, §8 | `references/supervise.md` | before the first supervision sweep |

---

## §0 Invariants — reread every sweep, never work from memory

1. **The state file is the only truth.** `~/.omp/dispatch-opencode/<run-id>/state.json`. Begin every
   sweep by reading it; OMP conversation memory may have been compacted away. Rewrite it atomically
   (write `.tmp`, then `mv`) at the end of every sweep.
2. **Judge a lane from disk and native agent status.** Safe approval posture by default.
   Lane status from `herdr agent get` (`agent_status`, `agent_session`) and verified disk state are
   the authoritative signals.
3. **`agent_status` alone never means "finished", and it can lie outright.** Always corroborate
   (§6). An idle or done agent has merely settled its current turn; check `.dispatch/DONE` and run
   independent verification before concluding anything.
4. **Never touch what you did not create.** Act only on ids recorded in the state file. Never
   `herdr server stop`. Never `herdr agent focus` / `workspace focus`.
5. **Never destroy work; publish only what the user authorized.** Default posture: **no push, no PR.**
   A verified lane stays `verified` until the user passes `--push` (or explicitly authorizes per
   lane). The push operation is always yours to run, never the lane's.
6. **No goal mode.** OpenCode does not have autonomous cross-turn goal execution. The supervision
   sweep is the engine that drives multi-turn progress.

---

## §1 Gate and parse

Run `test "${HERDR_ENV:-}" = 1`, `test -n "${HERDR_PANE_ID:-}"` and `herdr agent list`. If either
env var is unset or the CLI cannot reach the socket, stop and tell the user in Chinese that this
session is not inside a Herdr pane — an OMP session outside Herdr has nothing to dispatch into.
Do not install or launch Herdr, and do not run OpenCode yourself.

Parse flags from the raw request; everything else is task text.

| Flag | Meaning | Default |
| --- | --- | --- |
| `--lanes N` | cap on concurrent lanes, 1–16 | 16 |
| `--base <ref>` | base ref for lane branches | `origin/<current>` if it exists, else current branch |
| `--auto` / `--yolo` | explicitly auto-approve permissions in OpenCode | **off — safe manual approval is default** |
| `--push` | push each verified lane to origin (and open PR if `gh` is authenticated) | **off — no-push is default** |
| `--no-loop` | do not arm the recurring supervision loop after dispatch | off |
| `--resume` | skip §2–§5; run ONE supervision sweep over the existing state file | off |

**Every lane gets its own git worktree via `herdr worktree create`. This is not a flag and there is no opt-out.**
If the request contains `--no-worktree`, stop before creating anything and explain in Chinese.

With `--resume`, scan `~/.omp/dispatch-opencode/*/state.json` for runs whose repo matches the cwd
with non-terminal lanes; one match sweeps it, several → ask user which, none → say so and stop.
Read `references/driver.md` and `references/supervise.md` then go to §6.

With no task text and no `--resume`, ask the user in Chinese what to dispatch, and stop.

Otherwise — fresh dispatch — read `references/plan.md` and continue at §2.
