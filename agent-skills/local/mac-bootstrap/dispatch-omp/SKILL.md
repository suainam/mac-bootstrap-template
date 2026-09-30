---
name: dispatch-omp
description: From an OMP session inside a Herdr pane, dispatch one or more tasks to OMP worker agents running in isolated git worktrees — plan, supervise, and independently verify each lane to completion without touching the user's checkout or pushing to remote. Use when the user asks to dispatch/fan out/派发 tasks to OMP via Herdr lanes, or to resume supervision of an existing run (`--resume`). Fails clearly outside a Herdr pane. Note: Pi worker is not implemented; pi CLI is absent on this machine.
argument-hint: '<task-1>; <task-2>; … [--lanes N] [--base <ref>] [--no-loop] [--push] [--resume]'
---

# Dispatch tasks to OMP agents running under Herdr — OMP edition

The **raw request** is the text passed to this skill — its arguments, or when invoked with none,
the task text in the user's own message.

You are an **orchestrator**. You do not implement the tasks yourself. You split the request into
lanes, give each lane its own Herdr workspace and its own OMP worker agent, independently verify the
result, and report. **The lane's DONE claim never grants completion — you re-run the agreed checks
yourself (§6e).**

This skill is derived from `dispatch-codex` and adapted for OMP workers: state lives under
`~/.omp/dispatch-omp/`, `ask` replaces `AskUserQuestion`, OMP's own loop mode replaces the upstream
loop skill, and **push/PR is disabled by default** (pass `--push` to enable after parent verification).

> **Pi worker status**: Pi worker is not implemented in this driver; `pi` CLI is absent on this machine.
> Per ticket #115 / #109 spec, a separate `dispatch-pi` skill is required when `pi` becomes available.

## How to read this skill

Section numbers (§0–§8) are continuous across all four files:

| Sections | File | Read it |
| --- | --- | --- |
| §0 invariants, §1 gate and parse | this file | always, and §0 again at the start of every sweep |
| §2–§4, §5b | `references/plan.md` | fresh dispatch only, before creating anything |
| §5a, §5c, §6a, §6c, §6d, §6g, §6h | `references/driver.md` | everything OMP worker-specific |
| §6b, §6e, §6f, §6i, §7, §8 | `references/supervise.md` | before the first supervision sweep |

---

## §0 Invariants — reread every sweep, never work from memory

1. **The state file is the only truth.** `~/.omp/dispatch-omp/<run-id>/state.json`. Begin every
   sweep by reading it; OMP conversation memory may have been compacted away. Rewrite it atomically
   (write `.tmp`, then `mv`) at the end of every sweep.
2. **Judge a lane from disk, not from the screen.** OMP worker writes session JSONL files under
   its isolated lane session directory `~/.omp/dispatch-omp/<run-id>/sessions/<lane>/`. Terminal output
   is the fallback, never the primary signal.
3. **`agent_status` alone never means "finished", and it can lie outright.** Always corroborate
   (§6).
4. **Never touch what you did not create.** Act only on ids recorded in the state file. Never
   `herdr server stop`. Never `herdr agent focus` / `workspace focus`.
5. **Never destroy work; publish only what the user authorized.** Default posture: **no push, no PR.**
   A verified lane stays `verified` until the user passes `--push` (or explicitly authorizes per
   lane). The push operation is always yours to run, never the lane's.
6. **Session files can grow large.** Never parse one whole — read only the tail.

---

## §1 Gate and parse

1. Run `test "${HERDR_ENV:-}" = 1`, `test -n "${HERDR_PANE_ID:-}"` and `herdr agent list`. If either
   env var is unset or the CLI cannot reach the socket, stop and tell the user in Chinese that this
   session is not inside a Herdr pane — an OMP session outside Herdr has nothing to dispatch into.
   Do not install or launch Herdr, and do not run worker agents yourself.
2. Run `omp --version`. If `omp` CLI is not found or fails, stop and tell the user in Chinese that
   `omp` CLI is missing or not functioning.
3. Note on Pi: Pi worker is not supported (not installed). If the user explicitly requests Pi worker
   dispatch, stop and explain in Chinese that `pi` CLI is not installed on this machine and Pi dispatch
   is unavailable until a separate `dispatch-pi` skill is added.

Parse flags from the raw request; everything else is task text.

| Flag | Meaning | Default |
| --- | --- | --- |
| `--lanes N` | cap on concurrent lanes, 1–16 | 16 |
| `--base <ref>` | base ref for lane branches | `origin/<current>` if it exists, else current branch |
| `--no-yolo` | run with safe approval handling (interactive prompt confirmation) | on — **safe approval is default** |
| `--yolo` | auto-approve tool execution (only when explicitly requested) | off |
| `--push` | push each verified lane to origin (and open PR if `gh` is authenticated) | **off — no-push is default** |
| `--no-loop` | do not arm the recurring supervision loop after dispatch | off |
| `--resume` | skip §2–§5; run ONE supervision sweep over the existing state file | off |

**Every lane gets its own git worktree. This is not a flag and there is no opt-out.** If the
request contains `--no-worktree`, stop before creating anything and explain in Chinese.

With `--resume`, scan `~/.omp/dispatch-omp/*/state.json` for runs whose repo matches the cwd
with non-terminal lanes; one match sweeps it, several → ask user which, none → say so and stop.
Read `references/driver.md` and `references/supervise.md` then go to §6.

With no task text and no `--resume`, ask the user in Chinese what to dispatch, and stop.

Otherwise — fresh dispatch — read `references/plan.md` and continue at §2.
