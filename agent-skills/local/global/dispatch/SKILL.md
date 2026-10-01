---
name: dispatch
description: Dispatch tasks to heterogeneous agents (Codex, OpenCode, Claude Code, Antigravity, OMP) running in Herdr-managed isolated worktrees. Features task-based model routing, quota failover, two-step trust handshake, zero-token watchdog supervision, and fire-and-yield handoff. Use when dispatching implementation, refactoring, review, PR release, or audit tasks to background agents.
argument-hint: '--task <file> [--role <writer|skeptic|researcher>] [--kind <codex|opencode|claude|agy|omp>] [--model <model>] [--name <name>] [--base <ref>] [--auto] [--cwd <path>]'
---

# Unified Agent Dispatch & Orchestration Engine

You are the **Orchestrator**. You split work into isolated lanes, select the best agent kind and reasoning effort, dispatch via Herdr, supervise with a zero-token watchdog, and yield immediately to keep the conversation interactive.

---

## Architecture & Quick Reference

Progressive disclosure structure:
- **Diamond Governance & Role Boundaries**: [references/diamond.md](references/diamond.md)
- **Task-to-Model Routing Matrix & Quotas**: [references/routing.md](references/routing.md)
- **Protocol: Two-Step Handshake & Notify-Back**: [references/protocol.md](references/protocol.md)
- **Supervision: Fire-and-Yield & Todo Blocker**: [references/supervision.md](references/supervision.md)
- **Orchestrator Antipatterns & Failure Traps**: [references/antipatterns.md](references/antipatterns.md)
- **Session Memory & Anti-Amnesia Protocol**: [references/orchestrator-memory.md](references/orchestrator-memory.md)
- **Observability & Sub-Worker Telemetry**: [references/observability.md](references/observability.md)
- **End-to-End Production Scenarios**: [examples/workflow.md](examples/workflow.md)

---

## 1. Orchestrator Core Protocol

Follow the 5-phase lifecycle in sequence:

```
[Phase 1: Goal Contract] ──► [Phase 2: Topology & Handshake] ──► [Phase 3: Prompt & Block] ──► [Phase 4: Yield & Supervision] ──► [Phase 5: Harvest & Gate]
```

> **Resolving the gate plugin.** Phases 2 and 5 call
> `<TEMPLATE_ROOT>/multiplexer/herdr-dispatch/bin/dispatch_plugin.py`. This skill
> is installed independently of the template repo, so resolve the root once and
> fail loudly rather than skipping the gate:
> ```bash
> TEMPLATE_ROOT="${TEMPLATE_ROOT:-$(git -C "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" rev-parse --show-toplevel 2>/dev/null)/template}"
> GATE="${TEMPLATE_ROOT}/multiplexer/herdr-dispatch/bin/dispatch_plugin.py"
> [ -f "$GATE" ] || { echo "dispatch: cannot locate $GATE — set TEMPLATE_ROOT to the mac-bootstrap checkout" >&2; exit 2; }
> ```
> The gate is a refusal, not a formality: exiting 2 means the rule refused this
> dispatch, and proceeding anyway is the exact failure the gate was added to stop.

### Phase 1: Goal Contract & State Gate
Formulate a structured specification following `/skill:qiaomu-goal-meta-skill` (Outcome, Verification, Constraints, Boundaries, Iteration Policy, Stop when, Pause if).
```bash
# Mechanically assert all 7 sections exist and no raw diff blocks:
python3 scripts/dispatch.py lint "$TASK_FILE" || exit 1
# Advance orchestrator state machine:
python3 scripts/dispatch.py state advance --to-phase writer_implementation --repo "$PWD"
```

### Phase 2: Panel Topology & Two-Step Trust Handshake
1. **Provision Panel**:
   - Writer/Skeptic: Worktree isolation is mandatory. Run `herdr worktree create --cwd <repo> --branch <branch> --label <name> --no-focus`.
   - **Assert the isolation claim first** (1 Lane = 1 Worktree = 1 Branch). This exits 2 on a shared worktree or branch, and MUST abort the dispatch:
     ```bash
     python3 "$GATE" claim --lane <lane-id> --worktree <worktree-path> --branch <branch> || exit 2
     ```
     Sharing a worktree lets one lane merge the other's untested WIP and lets a
     finishing lane physically delete the directory its peer is still using.
   - Researcher: Non-interactive stdout query (`opencode run --auto "<query>"` / `agy -p "<query>"`). Never create worktrees for read-only probes.
2. **Start Interactive Agent**:
   Follow exact bare-binary CLI arguments in [references/routing.md](references/routing.md) and [references/protocol.md](references/protocol.md).
   - `opencode`: `--auto` (NO `-m` or `--model`)
   - `claude` / `agy`: `--model <model> [--dangerously-skip-permissions]`
   - `codex`: `-m <model>`
3. **Inspect-on-Failure Gate**:
   If startup fails or times out, read visible screen (`herdr pane read "$PANE" --source visible`) before touching anything.
4. **Resolve Trust Modal**:
   Send enter if `Accessing workspace...` prompt appears until interactive composer prompt (`❯`, `›`, `>`, `Ask anything...`) is confirmed.

### Phase 3: External File Prompt & Todo Blocker Guard
1. **External Contract & Explicit Coordinate Injection**:
   The orchestrator MUST dynamically inspect its own pane ID via `ORCH_PANE="$(herdr pane current | jq -r '.result.pane.pane_id')"`.
   Write long prompts/tasks to `.dispatch/TASK.md` or `/tmp/<task>.md`. Inject task reference with evaluated parent coordinate:
   ```bash
   herdr agent prompt <name> "Read .dispatch/TASK.md. When complete, write ~/Documents/handoffs/<name>-handoff-$(date +%Y%m%d_%H%M%S).md and run:
   herdr agent prompt ${ORCH_PANE} '\n[NOTIFY] [<pane_id>_<agent_kind>_<repo_slug>]\nDONE: <one-liner conclusion>\nHandoff: ~/Documents/handoffs/<handoff-filename>'"
   ```
   *(NEVER inject raw `<orch_pane_id>` or unevaluated placeholders; bind actual pane coordinate to avoid misrouting).*
2. **Todo Blocker Invariant**:
   If tracking progress via `todo`, you MUST block the waiting task to prevent harness reminder loops:
   ```bash
   todo(op="block", task="<task>", reason="Awaiting background child agent <name> IPC [NOTIFY]")
   ```

### Phase 4: Fire-and-Yield Supervision
- **Yield immediately**: The `herdr agent prompt` call and `todo(op="block")` are terminal actions. Stop and yield control to user.
- **Zero-Token L2 Watchdog**: Run `herdr agent get <name>` only on suspected stall ($\ge$ 10 min without state change). Details in [references/supervision.md](references/supervision.md).

### Phase 5: Result Harvest & Human Gate
1. **Unblock Todo**: `todo(op="unblock", task="<task>")` when `[NOTIFY]` arrives or when harvesting.
2. **Anti-Worktakeover**: Read child handoff (`~/Documents/handoffs/...`) or pane buffer (`herdr pane read <pane> --source recent-unwrapped --lines 120`). Never re-run investigations or re-read code already explored by the child worker.
3. **Review Convergence Ceiling**: Max ONE round of review + ONE round of rework verification. Do NOT spawn infinite reviewer loops.
4. **Closeout Lifecycle Gate (Issue #121)**: NEVER run `herdr pane close` or remove the worktree before the gate opens. A worker being alive, working, or merely slow is NOT evidence that closeout is done — closing early drops the child push, the parent pointer update and the PR merge on the floor.
   ```bash
   # docs aligned -> child pushed -> parent pointer -> PR merged -> worktree removed
   python3 "$GATE" closeout --lane <lane-id> \
     --evidence '{"docs_aligned":{"docs_reconciled":true}, ...}' || exit 2
   ```
   Exit 2 means the worker pane **must stay open**; fix the reported step first. An unproven step is not a passed step.
5. **Human Gate**: Strictly no `git push` or PR merge without explicit human authorization.
