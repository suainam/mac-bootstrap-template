# herdr-dispatch

Herdr-native lane orchestration for the dispatch family, plus the orchestrator
brain state machine that keeps the orchestrator from doing the workers' jobs.

Status: TB-01 and TB-02 implemented. TB-03 onward is not here yet.

## What lives where

| Piece | Path | Shape |
|---|---|---|
| Orchestrator brain state store | `lib/orchestrator_state.py` | library + CLI, no daemon |
| Single-writer audit gate | `../../scripts/dispatch-single-writer-gate.py` | repo gate, wired into `make repo-check` |

## The orchestrator brain loop

Recording only worker tasks is what produced the antipatterns this loop exists
to remove. With no representation of "what am I doing right now", a todo
reminder reads as a demand for *new work* rather than a reminder about a task
that is deliberately parked, and the orchestrator responds by improvising:
probing state (false busywork), editing worker-owned code (child-work
takeover), or restating one worker's report (degraded relay).

So todos are layered. **Phase 0** is the orchestrator's own meta-task, a real
state machine:

```text
contract -> topology -> yield_and_guard -> synthesis -> decision -> human_gate -> closed
```

**Phase 1** is the per-lane business task dispatched to a worker. The two share
one state file so there is a single truth:

```text
<git-common-dir>/dispatch/ORCHESTRATOR_STATE.json   (schema 2)
```

Anchoring on the git *common* dir is what keeps a linked worktree and its main
checkout from growing two brains.

Two guards matter more than the field itself:

- **Leaving `yield_and_guard` needs a real wake signal** — a worker `[NOTIFY]`
  or a stall alarm. A todo reminder is explicitly not one. This is the false
  busywork loop, closed at the state machine rather than by asking the model to
  resist a prompt.
- **`human_gate` is only crossed by explicit human authorisation**, so no
  automatic path can publish.

An invalid phase is rejected and the previous state kept. A brain state that
silently falls back to a default is worse than none, because it looks
authoritative while being wrong.

## CLI

```bash
PY=.venv/bin/python   # or any python3.12+

$PY multiplexer/herdr-dispatch/lib/orchestrator_state.py path
$PY multiplexer/herdr-dispatch/lib/orchestrator_state.py advance --to topology
$PY multiplexer/herdr-dispatch/lib/orchestrator_state.py park --pane w3:p1 --lane 1-1
$PY multiplexer/herdr-dispatch/lib/orchestrator_state.py show --brain
$PY multiplexer/herdr-dispatch/lib/orchestrator_state.py wake --lane 1-1
$PY multiplexer/herdr-dispatch/lib/orchestrator_state.py migrate --dry-run
```

## Ownership boundaries

Writes are partitioned so the short-lived Herdr plugin process and the
long-lived omp extension cannot clobber each other:

| Writer | May write |
|---|---|
| Herdr plugin (`update_lane(writer="plugin")`) | lane `tokens`, `status`, `pane_id`, `agent_name` |
| omp extension (`update_lane(writer="extension")`) | lane `phase`, `handoff`, `notified_at` |
| omp extension only | Phase 0 (`orchestrator_phase`, `blocked_reason`, `brain`, `active_panes`) |

Crossing a partition raises rather than silently dropping the write.

Agent **lifecycle** reporting is not in this table on purpose: Herdr's own
`herdr:omp` integration owns it, and
`make dispatch-single-writer-gate` fails the build if dispatch code takes it
over. For the same reason dispatch records an expected resume command but never
attaches one itself.

## Install

```bash
make omp-extensions     # links local extensions into $PI_CODING_AGENT_DIR/extensions
```

Local extensions are symlinked from this repository, so the repo stays their
single source of truth: they are never fetched or version-resolved, and a
registry update cannot replace them.

## Tests

```bash
.venv/bin/python -m pytest tests/test_dispatch_orchestrator_state.py \
                             tests/test_dispatch_single_writer_gate.py \
                             tests/test_install_omp_extensions_local.py -q
```