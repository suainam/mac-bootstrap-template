# herdr-dispatch

Herdr-native lane orchestration for the dispatch family, plus the orchestrator
brain state machine that keeps the orchestrator from doing the workers' jobs.

Status: TB-01 and TB-02 implemented. TB-03 onward is not here yet.

## What lives where

| Piece | Path | Shape |
|---|---|---|
| Orchestrator brain state store | `lib/orchestrator_state.py` | library + CLI, no daemon |
| Lane isolation gate | `lib/lane_isolation.py` | pure policy; claims a worktree+branch or raises |
| Closeout lifecycle gate | `lib/closeout_gate.py` | pure policy; decides, never destroys |
| Single-writer audit gate | `../../scripts/dispatch-single-writer-gate.py` | repo gate, wired into `make repo-check` |
| omp-side extension | `agent/omp/extensions/dispatch-omp/` | in-process; brain loop, routing, gate, heartbeats |
| Context & memory governance | [`docs/memory-governance.md`](docs/memory-governance.md) | pure policy; pruning, rollover, downgrading, host pressure |
| Research register | [`docs/research-register.md`](docs/research-register.md) | what fed this design, and what is deferred to an issue |

## Memory governance

Dispatch fails from host memory exhaustion before it fails from bad prompts: a
long agent at 300–500k context tokens sits at 1.5–3 GB RSS, and four in
parallel is 6–12 GB. The kernel's response is a `SIGKILL` that looks like an
agent failure.

Four defences ship as policy in `governance.ts` — stage-boundary pruning,
session rollover, phase-aware model downgrading, and host-pressure admission
gating. See [docs/memory-governance.md](docs/memory-governance.md).

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

## Lane isolation: 1 Lane = 1 Worktree = 1 Branch

Two interactive agents in one worktree produce three failures that none of them
name as a cause: the lane that finishes first mechanically merges the other's
untested WIP; the lane that finishes first then physically deletes the directory
its peer is still testing in; and both hold the submodule dirty, so each one's
`worktree-init` gate refuses the other's and the pair deadlocks.

So the rule is a check, not prose. A lane claims a `(worktree, branch)` pair
before dispatch, and `lib/lane_isolation.py` refuses — loudly, `exit 2` — when
either half is already held by a **live** lane:

```bash
$PY multiplexer/herdr-dispatch/bin/dispatch_plugin.py claim \
  --lane 1-2 --worktree /tmp/nat-hk96 --branch feat/1-2
# dispatch: lane 1-2: worktree /private/tmp/nat-hk96 is already claimed by live
# lane '1-1'; 1 Lane = 1 Worktree = 1 Branch forbids sharing a worktree between
# interactive agents
# exit 2
```

Paths are compared after resolution, so `./wt`, a trailing slash and an absolute
path all collide with each other. A lane renewing its *own* claim is a no-op,
and a `closed` / `released` / `orphaned` lane frees its claim for the next run.

## Closeout Lifecycle Gate (Issue #121)

"Premature pane destruction" is the same shape of bug: the feature works, the
orchestrator wants the memory back, it closes the pane, and the push, the parent
pointer update and the PR merge never happen. Destroying the pane is
irreversible and it is the *last* step, so it is the step that must be gated
hardest — a worker may be alive, working, or merely slow, and none of those are
evidence that closeout is done.

Five steps, in order, each gated on facts the caller supplies:

```text
docs_aligned -> child_pushed -> parent_pointer_updated -> pr_merged -> worktree_removed
```

```bash
$PY multiplexer/herdr-dispatch/bin/dispatch_plugin.py closeout --lane 1-1
#   [BLOCK] docs_aligned: authoritative docs aligned with the change
#          unproven: docs_reconciled not reported (an unproven step blocks closeout)
#   [BLOCK] child_pushed: ...
#          not reached: an earlier closeout step is unmet
#   gate CLOSED at docs_aligned: the worker pane must stay open until this step passes
# exit 2
```

Two properties make this more than a checklist:

- **An unproven step is not a passed step.** A missing fact blocks; nothing is
  inferred from its absence. This is the fail-loud rule from the orchestrator
  lessons doc, applied to closeout.
- **The order is enforced.** An unpushed child *also* means the worktree still
  exists, but the reason to fix it is the push. Later steps report "not reached"
  rather than as independently broken, so nobody is told to delete a worktree
  whose commit was never pushed.

The gate **decides and never acts**: it runs no `git push`, `gh pr merge`,
`git worktree remove` or `herdr pane close`. A gate that performs the
irreversible action cannot also be the thing that audits it.

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
                             tests/test_dispatch_lane_isolation_closeout_gate.py \
                             tests/test_install_omp_extensions_local.py -q
```