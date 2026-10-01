# Context & Memory Governance

Multi-agent dispatch does not fail from bad prompts first. It fails from the
host running out of memory.

## The failure

A long agent keeps terminal output, diffs and tool results in process memory.
Past roughly 300–500k context tokens a single Node/Bun/Python agent commonly
sits at **1.5–3 GB RSS**. Four in parallel is **6–12 GB** before any of them
does useful work. On a 16 GB machine the kernel reclaims that with `SIGKILL`,
mid-task, and the task looks like an agent failure when it is really
host pressure.

Two properties make this worse:

- **Growth is monotonic.** Without intervention, context only grows, so the
  process crosses the line eventually no matter how careful the agent is.
- **The symptom is invisible.** The pane still shows a running agent. Nothing
  reports "approaching the ceiling"; the process simply stops existing.

## Four defences

All implemented in `governance.ts` as pure policy, so each is testable without a
session and overridable from the plugin config directory.

### 1. Append-only pruning at stage boundaries

When a worker crosses a milestone ("research done, implementing"), most of the
recent context is spent: build errors already triaged, greps already answered.
It is pure memory liability.

Prune at the boundary, not continuously. Mid-stage the recent tool output is
still what the current step is reasoning over, and dropping it loses the
evidence the stage needs.

- soft ceiling **120k tokens** → prune
- settle back to **30–50k** per stage
- what pruning must **never** drop: `conclusions`, `file_pointers`,
  `open_questions`, `contract`, `lane_plan`

An unknown context size produces **no** prune. Unknown is not a licence to
discard work.

### 2. Session rollover

Past a hard ceiling, checkpoint and continue in a fresh small session rather
than growing one process without bound.

- hard ceiling **200k tokens** → checkpoint to `.dispatch/CHECKPOINT.json`,
  retire the old session, start fresh at ~20k
- the old session is **retired, not deleted** — an operator may want to read it
- rollover is deliberately a *later* trigger than pruning: it costs a process
  restart, so pruning carries the middle range

### 3. Phase-aware model downgrading

Waiting for a build or tailing a log does not need the largest model. Dropping
to a light one cuts token spend *and* the runtime heap holding it.

Safe to downgrade: `planning`, `waiting`, `polling`, `collecting`,
`rolling_log`, `applying`.

**Never** downgrade `verifying`, `review`, `skeptic`, `deciding`. This is the
point of the whole rule: memory pressure must not quietly trade correctness
away. The only override is `critical` host pressure, and when it applies the
reason says so explicitly rather than pretending the stage was mechanical.

### 4. Host memory pressure

The watchdog watches headroom and stops *admitting* agents before the host is
forced to kill one.

| Free memory | Pressure | Effect |
|---|---|---|
| ≥ 20% | `ok` | everything admitted |
| 10–20% | `elevated` | **heavy** agents refused, light ones still admitted |
| < 10% | `critical` | no new agents admitted |

A total stop at `elevated` would strand the orchestrator with no way to make
progress, which is why light agents keep flowing.

An unprobeable host yields **no opinion**, never a fabricated `critical` — a
failed probe must not freeze every lane.

## What this deliberately does not do

- **No automatic model switching mid-turn.** Downgrading happens at a stage
  boundary, where the context is already summarised.
- **No silent pruning of the orchestrator's own brain state.** Phase 0 and the
  contract are retained by construction.
- **No killing of running agents.** Pressure gates *admission*. Terminating
  someone's in-flight work to save memory trades a known cost for an unknown one.

## Relationship to the stall watchdog

They look similar and are not the same thing:

| | Stall watchdog | Context pressure |
|---|---|---|
| Symptom | pane quiet | pane busy but enormous |
| Cause | worker stopped reporting | context exceeded a budget |
| Response | inspect, nudge, abort, re-dispatch | prune, roll over, downgrade, throttle |

## Configuration

Every threshold is overridable; the defaults are deliberately conservative,
because a memory fix applied too eagerly costs more than the memory it saves.

```json
{
  "pruneThresholdTokens": 120000,
  "rolloverThresholdTokens": 200000,
  "targetStageTokens": 50000,
  "memoryPressureFloor": 0.20,
  "criticalPressureFloor": 0.10
}
```