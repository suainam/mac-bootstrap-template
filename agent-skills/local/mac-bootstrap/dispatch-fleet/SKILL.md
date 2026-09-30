---
name: dispatch-fleet
description: Orchestrate heterogeneous agent lanes (Codex, OpenCode, Claude Code, Antigravity, OMP) concurrently in separate Herdr worktrees. Supervise lanes across distinct lifecycles, independently verify each lane's agreed criteria, enforce local isolation without focus stealing, and guard publication boundaries (no-push/no-PR default). Use when dispatching multi-task or multi-agent workflows across different worker kinds or managing concurrent Herdr lanes.
argument-hint: '<lane-1:kind:task>; <lane-2:kind:task>; … [--base <ref>] [--yolo] [--no-loop] [--push] [--resume]'
---

# Heterogeneous Lane Dispatch & Supervision — OMP Edition (#116)

Orchestrate and supervise concurrent lanes across multiple worker kinds (`codex`, `opencode`, `claude`, `agy`, `omp`) inside Herdr panes.

## Core Invariants

1. **Local Worktree Isolation**: Every lane MUST live in its own Git worktree created via `herdr worktree create`. No lane shares a worktree with the orchestrator or any other lane.
2. **Distinct Lifecycle State**: Each lane is tracked independently in `~/.omp/dispatch-fleet/<run-id>/state.json`. A failing or blocked lane NEVER affects a healthy lane or marks it verified.
3. **Independent Parent Verification**: Worker `DONE` claims never grant completion. The orchestrator re-executes each lane's agreed criteria independently.
4. **Publication Boundary**: Strictly NO PUSH and NO PR by default. A lane is marked `verified_local`. Remote publication requires explicit `--push` authorization at dispatch time, and applies only to lanes that passed parent verification.
5. **Focus Protection**: Background lanes run without stealing focus (`--no-focus`), allowing the human or orchestrator to work undisturbed.
6. **No Leaked Workspaces**: All temporary worktrees and workspaces must be cleaned up via `herdr worktree remove --workspace <ws> --force` or reported clearly upon exit.

## Worker Drivers

Lanes delegate execution to their respective worker drivers:
- `codex`: Goal mode or single prompt; rollout inspection in driver.md
- `opencode`: Nudge-driven execution with safe default permissions
- `claude`: Claude Code driver with native session tracking and resume
- `agy`: Antigravity CLI driver with integration check and session identity
- `omp`: OMP worker driver using isolated `--session-dir` storage
*(Pi worker is documented as unavailable until `pi` CLI is installed)*
