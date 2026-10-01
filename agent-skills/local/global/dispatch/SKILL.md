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
1. **Dispatch through the bus — do not hand-assemble a lane**:
   One command performs the contract lint, the claim gate, the pane rename, the
   timestamp mint, the `[NOTIFY]` envelope assembly, the brain state flush and the
   verified delivery. Any gate refuses, and **nothing** is renamed, written or sent.
   ```bash
   python3 "$GATE" --repo "$PWD" dispatch \
     --task "$TASK_FILE" --lane 1-3 --lane-name 1-3-dispatch \
     --target "$WORKER_PANE" --signature "1-3-dispatch_<agent_kind>" \
     [--worktree <path> --branch <branch>] \
     --highlight "<core result>" --risk "<leftover>"
   ```
   - `--lane-name` MUST match `^[0-9]+-[0-9]+-[a-z0-9_-]+$` (`1-2-sysctl`,
     `1-3-dispatch`). A bare slug like `research-agy` is refused, exit 2.
   - The handoff path is **generated**, never typed: `~/Documents/handoffs/<lane-name>-handoff-<YYYYMMDD_HHMMSS>.md`.
   - Exit `1` means the contract is malformed; exit `2` means a rule refused.
     Exit `1` is "fix your task file"; exit `2` is "this lane is unsafe".

2. **Provision Panel**:
   - Writer/Skeptic: Worktree isolation is mandatory. Run `herdr worktree create --cwd <repo> --branch <branch> --label <name> --no-focus`.
   - **Assert the isolation claim first** (1 Lane = 1 Worktree = 1 Branch). This exits 2 on a shared worktree or branch, and MUST abort the dispatch:
     ```bash
     python3 "$GATE" claim --lane <lane-id> --worktree <worktree-path> --branch <branch> || exit 2
     ```
     Sharing a worktree lets one lane merge the other's untested WIP and lets a
     finishing lane physically delete the directory its peer is still using.
     *(The `dispatch` bus above already runs this gate — invoke it directly only
     when claiming a worktree outside a dispatch.)*
   - Researcher: Non-interactive stdout query (`opencode run --auto "<query>"` / `agy -p "<query>"`). Never create worktrees for read-only probes.
3. **Start Interactive Agent**:
   Follow exact bare-binary CLI arguments in [references/routing.md](references/routing.md) and [references/protocol.md](references/protocol.md).
   - `opencode`: `--auto` (NO `-m` or `--model`)
   - `claude` / `agy`: `--model <model> [--dangerously-skip-permissions]`
   - `codex`: `-m <model>`
4. **Inspect-on-Failure Gate**:
   If startup fails or times out, read visible screen (`herdr pane read "$PANE" --source visible`) before touching anything.
5. **Resolve Trust Modal**:
   Send enter if `Accessing workspace...` prompt appears until interactive composer prompt (`❯`, `›`, `>`, `Ask anything...`) is confirmed.

### Phase 3: External File Prompt & Todo Blocker Guard
1. **External Contract & Explicit Coordinate Injection**:
   The orchestrator MUST dynamically inspect its own pane ID via `ORCH_PANE="$(herdr pane current | jq -r '.result.pane.pane_id')"`.
   Write long prompts/tasks to `.dispatch/TASK.md` or `/tmp/<task>.md`. Inject task reference with evaluated parent coordinate:
   ```bash
   herdr agent prompt <name> "Read .dispatch/TASK.md and implement the fix. When complete, write ~/Documents/handoffs/<name>-handoff-$(date +%Y%m%d_%H%M%S).md and report back with the notify command below."
   ```
   *(NEVER inject raw `<orch-pane_id>` or unevaluated placeholders; bind actual pane coordinate to avoid misrouting).*

2. **Prompt Protocol Gate (mechanical, not advisory)**:
   **Do not call `herdr agent prompt` directly.** Herdr exposes no pre-prompt hook —
   `agent prompt` is a direct CLI/RPC call and the plugin event surface is a fixed
   set of state-change notifications — so nothing can intercept a prompt sent
   behind the plugin's back. The gate is therefore the **sanctioned send path**:
   ```bash
   # validate then deliver; refuses with exit 2 BEFORE delivery
   printf '%s' "$PROMPT" | python3 "$GATE" prompt --stdin --send --target "$WORKER_PANE" || exit 2
   # check only, no delivery
   printf '%s' "$PROMPT" | python3 "$GATE" prompt --stdin || exit 2
   ```
   Every dispatched prompt needs a **resolved** coordinate (`w<N>:p<N>`, never
   `${ORCH_PANE}` or `<orch-pane>`) and a structured `[NOTIFY]` carrying `DONE:`
   and `Handoff:` lines. Validation judges only; on delivery the gate expands
   literal `\n` / `\r` / `\t` into real control characters so the report renders
   as multiple lines. Use `--keep-escapes` to send bytes verbatim.

3. **Reporting back — use the `notify` command, never a hand-quoted `[NOTIFY]`**:
   ```bash
   python3 "$GATE" notify \
     --signature "<pane_id>_<agent_kind>_<repo_slug>" \
     --done "<one-line conclusion>" \
     --handoff "~/Documents/handoffs/<handoff-file>.md" \
     --target "$ORCH_PANE" \
     --highlight "<core result 1>" --highlight "<core result 2>" \
     --risk "<leftover 1>" \
     --send
   ```
   Emit the structure verbatim; do not retype it:
   ```text
   [NOTIFY] [<pane_id>_<agent_kind>_<repo_slug>]
   DONE: <一句话明确结论>
   Handoff: <handoff 绝对路径>
   回调目标坐标: <w<N>:p<N>>

   [核心成果与证据]
   - 重点 1: ...
   - 重点 2: ...

   [风险与遗留]
   - 遗留 1: ...
   ```

   > **Never write `herdr agent prompt w3:p1 '\n[NOTIFY] ...'`.** Bash single
   > quotes do not expand escapes, so `\n` reaches the worker as two literal
   > characters and the whole report renders as one long single line. That exact
   > mis-quoting shipped in this file for a long time. If you must use the raw
   > CLI, use `$'\n[NOTIFY] ...'` with **double**-inner/single-outer quoting —
   > but the `notify` command above is preferred, because it cannot be
   > mis-quoted and it renders the standard layout for you.
4. **Todo Blocker Invariant**:
   If tracking progress via `todo`, you MUST block the waiting task to prevent harness reminder loops:
   ```bash
   todo(op="block", task="<task>", reason="Awaiting background child agent <name> IPC [NOTIFY]")
   ```

### Phase 4: Fire-and-Yield Supervision
- **Yield immediately**: The `herdr agent prompt` call and `todo(op="block")` are terminal actions. Stop and yield control to user.
- **Zero-Token L2 Watchdog & Gate D Semantic Watchdog**: Check `herdr agent get <name>` on suspected stall ($\ge$ 10 min without state change). Gate D (`dispatch_plugin.py watchdog --lane <id>`) parses tail 15-line buffer via TypeSafe Jev System One: extends lease by 10 min if $P(\text{legitimate}) > 0.70$ (zero false alarms); sends soft nudge or aborts if $P(\text{stalled}) > 0.65$. Details in [references/supervision.md](references/supervision.md).

### Phase 5: Result Harvest & Human Gate
1. **Unblock Todo**: `todo(op="unblock", task="<task>")` when `[NOTIFY]` arrives or when harvesting.
2. **Anti-Worktakeover**: Read child handoff (`~/Documents/handoffs/...`) or pane buffer (`herdr pane read <pane> --source recent-unwrapped --lines 120`). Never re-run investigations or re-read code already explored by the child worker.
3. **Review Convergence Ceiling**: Max ONE round of review + ONE round of rework verification. Do NOT spawn infinite reviewer loops.
4. **Handoff Truthfulness Gate (Issue #132)**: run `verify-handoff` on the child's handoff BEFORE closeout. It decides physical facts in code (test exit code, git diff, claimed-vs-real scope) and sends only the semantic questions to Jev. Exits 2 when the Done claim is not corroborated, and prints a message naming the remedy — hand that message back to the worker.
   ```bash
   # Default is deterministic (heuristics). Add --online to also consult Jev.
   python3 "$GATE" verify-handoff --lane <lane-id> \
     --handoff ~/Documents/handoffs/<lane>-handoff-<ts>.md \
     --test-log /tmp/test.log --diff /tmp/change.diff \
     --exit-code <code-from-the-test-command> \
     --json > /tmp/truth.json || exit 2
   ```
   Notes: `--exit-code` is mandatory and is the fact that blocks first — do not omit it. `--diff` accepts a bare `git diff` patch, `--stat`, `--numstat` or `--name-only`. `--expect-file` (repeatable) additionally refuses a handoff whose claimed scope the diff does not touch. Prefer the default: the live model over-blocks honest handoffs (measured p=0.47–0.58 against a 0.35 block line on `jev-1.13.0`), so `--online` is opt-in and its threshold consequences are the caller's to own.

5. **Closeout Lifecycle Gate (Issue #121)**: NEVER run `herdr pane close` or remove the worktree before the gate opens. A worker being alive, working, or merely slow is NOT evidence that closeout is done — closing early drops the child push, the parent pointer update and the PR merge on the floor.
   ```bash
   # handoff_truthful -> docs aligned -> child pushed -> parent pointer -> PR merged -> worktree removed
   python3 "$GATE" closeout --lane <lane-id> \
     --evidence '{"docs_aligned":{"docs_reconciled":true}, ...}' \
     --handoff-report /tmp/truth.json || exit 2
   ```
   Exit 2 means the worker pane **must stay open**; fix the reported step first. An unproven step is not a passed step.

   `--handoff-report` is the Gate C verdict from step 4. It is evaluated FIRST, before any lifecycle step, so an unverified lane cannot be pushed, merged or cleaned up. Omitting it is legal — callers that predate Gate C are unaffected — but the report then prints `[SKIP] handoff_truthful: not evaluated`, which is the gate telling you it never checked the handoff's truthfulness. Treat that line as a missing gate, not a pass.
6. **Human Gate**: Strictly no `git push` or PR merge without explicit human authorization.
