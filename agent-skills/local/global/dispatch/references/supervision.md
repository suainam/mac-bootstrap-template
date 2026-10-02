# Two-Tier Watchdog & Supervision Reference

## 1. Operating System Principles: Interrupts vs Polling

In distributed systems and operating system design, pure polling burns excessive cycles/tokens, while pure event-waiting risks unhandled deadlocks if a worker hangs silently.

The optimal strategy combines **Primary Event Interrupts** with **Secondary Zero-Token Watchdogs**:

```
                       ┌──────────────────────────────────────────────┐
                       │          Orchestrator (Main Session)         │
                       └───────────────┬──────────────────────────────┘
                                       │ Fire-and-Yield (0 Token Polling)
                                       ▼
           ┌────────────────────────────────────────────────────────────────────┐
           │ L1 Primary: Event-Driven Soft Interrupt                            │
           │ Child agent finishes turn → herdr agent prompt <orch-pane>         │
           │ Orchestrator woken immediately by incoming event message.          │
           └────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼ Only on Suspected Hang / Inactivity
           ┌────────────────────────────────────────────────────────────────────┐
           │ L2 Secondary: Zero-Token OS/Herdr Lifecycle Watchdog               │
           │ Query: herdr agent get <name> (Takes 5ms, costs 0 LLM Tokens)      │
           │ 1. agent_status == blocked  → Interactive modal trapped. Intervene.│
           │ 2. agent_status == idle     → Silent turn finish. Intervene.       │
           │ 3. state_change_seq stalled → Stalled/looping. Issue Nudge/Abort.  │
           └────────────────────────────────────────────────────────────────────┘

### Redline: Todo Blocker Guard (Suppressing Anxious Wakeups)
OMP and agent harness runtimes frequently maintain active `todo` monitoring (`todo.reminders = true`). If an orchestrator yields control while a task in `todo` remains active or pending, the harness automatically revives the session with stop reminders ("You have open todos!"), triggering an anxiety loop of empty probing.

**Invariant**:
Immediately before yielding control for background execution, the Orchestrator MUST block the waiting task:
```bash
# If managing state via todo:
todo(op="block", task="<current-task>", reason="Awaiting background child agent <name> IPC [NOTIFY]")
```
When the child agent's `[NOTIFY]` arrives or when harvesting output:
```bash
todo(op="unblock", task="<current-task>")
```
```

---

## 2. L2 Watchdog Diagnostics & Resolution Table

When inspecting `herdr agent get <name>`:

| Observed Signal | Root Cause | Orchestrator Remediation Action |
| :--- | :--- | :--- |
| `agent_status == blocked` | Trapped in trust modal or dangerous tool confirmation | Read visible screen via `herdr pane read <pane> --source visible`. If safe, send `enter` or `y`; if dangerous, surface to user. |
| `agent_status == idle` and no notify-back received | Agent finished turn but omitted notify-back or crashed | Inspect git status & `.dispatch/progress.md`. If criteria met, mark verified; otherwise send continuation nudge. |
| `state_change_seq` unchanged $\ge$ 10 min | Long compilation/test OR process hung | Run **Gate D: Semantic Watchdog** (`dispatch_plugin.py watchdog --lane <id>`). Evaluates tail 15-line buffer via TypeSafe Jev: if $P(\text{legit}) > 0.70$, extends lease by 10 min (0 false alarms); if $P(\text{stalled}) > 0.65$, sends `\n` soft nudge or aborts. |
| Visible screen contains rate limit pattern | Quota exhausted mid-turn | Capture signature, stop agent, relaunch task on failover agent kind. |

---

## 3. Fallback Sweep Backoff Formula

If passive background monitoring is mandated by policy or tests:
Never use a fixed interval (e.g. 10s). Use **Exponential Backoff with Jitter**:

$$T_{\text{interval}} = \min(60s,\ 5s \times 2^{\text{sweep\_attempt}}) + \text{jitter}(0, 2s)$$

Intervals scale: $5s \rightarrow 10s \rightarrow 20s \rightarrow 40s \rightarrow 60s$ (capped).
Reduces redundant token consumption by over 70%.

---

## 4. Gate A: PreToolUse Reflex Gate (Anti-Takeover)

The tables above tell the orchestrator what to do. **Gate A enforces it mechanically**, at the tool-call boundary, so an anti-pattern is refused rather than merely discouraged.

### The failure it prevents

Two behaviours, one cause — the orchestrator acting as if it were the worker:

| Anti-pattern | What it looks like | Why it is not the orchestrator's job |
| :--- | :--- | :--- |
| **代查强迫症 (child-work takeover)** | `read_file` on a lane's source while parked in `yield_and_guard`; `cat .worktrees/<lane>/src/app.py` | That code was dispatched to a lane. Re-doing it burns the tokens the lane is already spending. |
| **违规探针 (illegal probe)** | `git status`, `pytest`, `herdr agent get` on a running lane while parked | A probe whose result arrives is indistinguishable from one that justifies acting. |
| **Root-checkout destruction** | `git reset --hard` / `git clean -fd` in a canonical root | The root working tree is the **only** copy of what is uncommitted there. No lane can restore it. |

### Three layers, ordered by cost

| Order | Layer | Decides | Cost |
| :--- | :--- | :--- | :--- |
| **0** | **Destructive root check** | `git reset --hard` / `git clean -fd` / `rm -rf` outside a lane worktree | local, deterministic |
| 1 | Whitelist bypass | `todo`, `ORCHESTRATOR_STATE.json`, `~/Documents/handoffs/`, own task contract | local, no socket |
| 2 | Mechanical | business-code read while parked; a probe | local, deterministic |
| 3 | Jev semantics | `is_role_boundary_violation`, `is_illegal_probe_while_parked` (Noul) | one batched call, or offline heuristics |

Layers 2–3 exist for what the mechanical layer cannot settle. **Layer 0 runs before the bypass, and that ordering is deliberate**: the whitelist is a bypass, and a bypass placed ahead of it would let `cat handoffs/x.md && git reset --hard` through on the strength of the leading path. Spending a Jev round trip to learn that `git reset --hard` is destructive would be spending tokens on arithmetic.

### Where destructive commands are legal

**Only inside an isolated lane worktree**: `.worktrees/`, `.herdr/worktrees/`, or `worktrees/`.

```bash
herdr worktree create .worktrees/<lane-slug>   # then destructive work happens here
```

Refused in **every** brain phase, not just `yield_and_guard` — the park is not the only thing that should stand between a reset and a lost day. Read-only `git` (`status`, `diff`, `log`) is unaffected by this rule, and so are `--soft` / `--mixed` resets.

Two shapes defeat a naive check, and both are covered:

- **A worktree cwd is not enough.** `git -C <root> clean -fd` run from inside a lane worktree is still a root checkout. Isolation is judged from every directory the command names, not only from where it runs.
- **A management read is not a pass.** `cat handoffs/x.md && git reset --hard` is refused. The mechanical check runs *before* the whitelist, and the whitelist's path is normalised first, so `.dispatch/../src/app.py` cannot borrow a marker.### What a refusal looks like

A refusal returns `block: true` **and** injects a corrective steer naming the legal next action. The steer is the point: a block that only says "no" leaves the model to pick a replacement, and the cheapest replacement is the behaviour just refused. Expect it as an `aside` message, and obey it rather than retrying with a different tool.

### Manual check

```bash
# Exits 2 on refusal; --phase defaults to whatever the state file records
python3 multiplexer/herdr-dispatch/bin/dispatch_plugin.py gate \
    --phase yield_and_guard --tool read_file --target .worktrees/1-4/src/app.py
```
