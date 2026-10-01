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
