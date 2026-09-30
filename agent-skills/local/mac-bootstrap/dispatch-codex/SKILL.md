---
name: dispatch-codex
description: From an OMP session inside a Herdr pane, dispatch one or more tasks to Codex agents running in isolated git worktrees — plan, supervise, and independently verify each lane to completion without touching the user's checkout or pushing to remote. Use when the user asks to dispatch/fan out/派发 tasks to Codex via Herdr lanes, or to resume supervision of an existing run (`--resume`). Fails clearly outside a Herdr pane.
argument-hint: '<task-1>; <task-2>; … [--lanes N] [--base <ref>] [--no-yolo] [--no-loop] [--push] [--resume]'
---

# Dispatch tasks to Codex agents running under Herdr — OMP edition

The **raw request** is the text passed to this skill — its arguments, or when invoked with none,
the task text in the user's own message.

You are an **orchestrator**. You do not implement the tasks yourself. You split the request into
lanes, give each lane its own Herdr workspace and its own Codex agent, independently verify the
result, and report. **The lane's DONE claim never grants completion — you re-run the agreed checks
yourself (§6e).**

This skill is derived from upstream `bestony/herdr-dispatch` skills/_shared and dispatch-codex,
adapted for OMP: state lives under `~/.omp/dispatch-codex/`, `ask` replaces `AskUserQuestion`,
OMP's own loop mode replaces the upstream `loop` skill, and **push/PR is disabled by default**
(pass `--push` to enable after parent verification).

## How to read this skill

Section numbers (§0–§8) are continuous across all four files:

| Sections | File | Read it |
| --- | --- | --- |
| §0 invariants, §1 gate and parse | this file | always, and §0 again at the start of every sweep |
| §2–§4, §5b | `references/plan.md` | fresh dispatch only, before creating anything |
| §5a, §5c, §6a, §6c, §6d, §6g, §6h | `references/driver.md` | everything Codex-specific |
| §6b, §6e, §6f, §6i, §7, §8 | `references/supervise.md` | before the first supervision sweep |

---

## §0 Invariants — reread every sweep, never work from memory

1. **The state file is the only truth.** `~/.omp/dispatch-codex/<run-id>/state.json`. Begin every
   sweep by reading it; OMP conversation memory may have been compacted away. Rewrite it atomically
   (write `.tmp`, then `mv`) at the end of every sweep.
2. **Judge a lane from disk, not from the screen.** Codex writes a rollout JSONL. Terminal output
   is the fallback, never the primary signal.
3. **`agent_status` alone never means "finished", and it can lie outright.** Always corroborate
   (§6). The gap between auto-continued goal turns also reads `done` — one more reason `done` alone
   proves nothing.
4. **Never touch what you did not create.** Act only on ids recorded in the state file. Never
   `herdr server stop`. Never `herdr agent focus` / `workspace focus`.
5. **Never destroy work; publish only what the user authorized.** Default posture: **no push, no PR.**
   A verified lane stays `verified` until the user passes `--push` (or explicitly authorizes per
   lane). The push operation is always yours to run, never the lane's.
6. **Rollout files reach 100+ MB.** Never parse one whole — read only the tail.

---

## §1 Gate and parse

Run `test "${HERDR_ENV:-}" = 1`, `test -n "${HERDR_PANE_ID:-}"` and `herdr agent list`. If either
env var is unset or the CLI cannot reach the socket, stop and tell the user in Chinese that this
session is not inside a Herdr pane — an OMP session outside Herdr has nothing to dispatch into.
Do not install or launch Herdr, and do not run Codex yourself.

Parse flags from the raw request; everything else is task text.

| Flag | Meaning | Default |
| --- | --- | --- |
| `--lanes N` | cap on concurrent lanes, 1–16 | 16 |
| `--base <ref>` | base ref for lane branches | `origin/<current>` if it exists, else current branch |
| `--no-yolo` | launch Codex under user's approval config instead of bypassing it | off — **yolo is default** |
| `--yolo` | accepted, redundant | on |
| `--push` | push each verified lane to origin (and open PR if `gh` is authenticated) | **off — no-push is default** |
| `--no-loop` | do not arm the recurring supervision loop after dispatch | off |
| `--resume` | skip §2–§5; run ONE supervision sweep over the existing state file | off |

**Every lane gets its own git worktree. This is not a flag and there is no opt-out.** If the
request contains `--no-worktree`, stop before creating anything and explain in Chinese.

With `--resume`, scan `~/.omp/dispatch-codex/*/state.json` for runs whose repo matches the cwd
with non-terminal lanes; one match sweeps it, several → ask user which, none → say so and stop.
Read `references/driver.md` and `references/supervise.md` then go to §6.

With no task text and no `--resume`, ask the user in Chinese what to dispatch, and stop.

Otherwise — fresh dispatch — read `references/plan.md` and continue at §2.
