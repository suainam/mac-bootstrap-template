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
| Prompt protocol gate | `lib/prompt_protocol.py` | pure policy; judges, never rewrites |
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

## Prompt protocol gate — and why it is not an interceptor

An orchestrator sent bare prose straight through `herdr agent prompt` — no
evaluated coordinate, no `[NOTIFY]` contract — and the plugin system waved it
through. The worker got unstructured text where it expected a contract.

**The plugin could not have caught it, and that is the finding.** Herdr's plugin
surface is a fixed enumeration of *state-change* notifications (`pane.created`,
`pane.agent_status_changed`, `worktree.*`), declared as `[[events]] on = ...`.
`herdr agent prompt` is a direct CLI/RPC call: no pre-execution hook, no command
middleware, no veto anywhere in the plugin API. `agent.prompt` is an RPC
*command*, not an event, so a plugin cannot subscribe to it. Verified against the
full Herdr documentation, which contains zero interception points.

So the real defect was not a faulty validator — **there was no validator**. The
rule existed as prose in one section of `SKILL.md` and as nothing else.

What ships instead is the sanctioned path plus a check in front of delivery:

```bash
# validate then deliver; refuses with exit 2 BEFORE delivery
printf '%s' "$PROMPT" | python3 bin/dispatch_plugin.py prompt --stdin --send --target "$PANE"

# check only
printf '%s' "$PROMPT" | python3 bin/dispatch_plugin.py prompt --stdin
```

A dispatched prompt needs a **resolved** coordinate (`w<N>:p<N>` — never
`${ORCH_PANE}` or `<orch-pane>`) and a structured `[NOTIFY]` carrying `DONE:`
and `Handoff:` lines.

**Know what this does not give you.** A determined caller can still type
`herdr agent prompt` directly and bypass the gate entirely; nothing in Herdr can
stop that. What the gate does provide is a loud refusal at the point of use, a
delivery path that cannot leak a malformed prompt, and `SKILL.md` pointing at it
instead of at the raw CLI. Real enforcement needs an upstream Herdr hook.

Two deliberate properties:

- **It never repairs.** Substituting `${ORCH_PANE}` would fabricate a coordinate
  nobody verified, so the text handed to Herdr is byte-identical to the input.
- **It accepts the project's own template.** The canonical `SKILL.md` command
  writes `'\n[NOTIFY]...'`, and bash single quotes keep that a literal
  backslash-n. Structural checks run on an escape-normalised view; delivery
  always sends the original bytes.

`scripts/prompt-gate-probe.py` is the feedback loop that found all of this. It
distinguishes *"the gate refused this"* from *"the gate does not exist"* —
without that distinction argparse exits 2 for every input and the probe reports
green while nothing is being enforced.

## [NOTIFY] newline handling — the single-quote trap

```bash
herdr agent prompt w3:p1 '\n[NOTIFY] [w5:p1]\nDONE: landed\nHandoff: /tmp/x.md'
```

Bash single quotes do not expand escapes. That `\n` reaches the worker as **two
literal characters**, so the report renders as one long single-line string. This
form shipped in `SKILL.md` and `references/protocol.md` for a long time before
anyone noticed, because the message still *arrives* — it just arrives mangled.

Two ways out, in order of preference:

```bash
# 1. let the plugin render the report — cannot be mis-quoted
python3 bin/dispatch_plugin.py notify \
  --signature "<pane_id>_<agent_kind>_<repo_slug>" \
  --done "<one-line conclusion>" \
  --handoff "~/Documents/handoffs/<file>.md" \
  --target w3:p1 \
  --highlight "<core result>" --risk "<leftover>" --send

# 2. raw CLI with correct quoting ($'...' expands, '...' does not)
herdr agent prompt w3:p1 $'\n[NOTIFY] [w5:p1]\nDONE: landed\nHandoff: /tmp/x.md'
```

`prompt --send` also expands standard escapes on delivery, so a
single-quoted payload is repaired even if it reaches the gate. Use
`--keep-escapes` to opt out.

### When a note still appears after delivery

`prompt --send` prints a note when backslash escapes remain literal in the
delivered text. There are two causes, and the note names both:

- the escapes are inside a **fenced code block**, left verbatim on purpose;
- the text contains a **doubled backslash** (`\\n`), which is not expanded
  because shell `$'...'` owns that escape.

In the second case, write a **single** `\n` for a real line break. This is not a
failure — it usually means the payload arrived through a layer that already
consumed one level of escaping.

### What expansion does, and deliberately does not do

`normalise_escapes` expands **only** `\n`, `\r` and `\t`, and only outside fenced
code blocks. Each exclusion cost something to learn:

- **Not `encode().decode('unicode_escape')`.** That round-trips through latin-1
  and turns UTF-8 into mojibake: `修复完成` comes out as `ä¿®å¤å®`. Every report
  this gate carries is Chinese, so the obvious one-liner destroys the payload.
- **Not `\\`.** Shell `$'...'` already collapses it. Expanding it here makes
  `\\n` ambiguous between "escaped backslash + n" and "backslash-n escape", and
  silently breaks idempotence — `path\\name` would come back as
  `path<newline>ame`.
- **Fenced code is untouched.** A shell sample containing `'\n[NOTIFY]'` must
  survive verbatim, or the reader copies a deformed command.
- **Unknown escapes are preserved**, never interpreted.

`scripts/notify-format-probe.py` is the red-capable loop. It points
`HERDR_BIN_PATH` at a recorder so it captures the exact bytes that would reach
Herdr, and asserts real `0x0A` newlines, zero literal `\n`, byte-exact Chinese,
and an intact report structure.

> The `claim`, `closeout` and `prompt-check` manifest actions cannot take
> arguments (a manifest `command` is a fixed argv array), so they exit 2 when
> invoked from the action palette. Invoke them from the CLI as `SKILL.md`
> documents. `notify` is deliberately *not* registered as an action for the
> same reason.

## Orchestrator permission gate

The orchestrator is the one participant that can ruin a lane without touching a
lane's files. Probing `git status`, re-reading child code, polling worker panes —
that is work the *worker* was dispatched to do, and doing it as the orchestrator
produces the false-busywork loop from lesson 1 and child-work takeover from the
governance doc.

So orchestrator behaviour is a whitelist keyed on the brain phase, enforced by
`lib/orchestrator_guard.py` rather than by asking the model to resist a prompt:

```bash
$PY multiplexer/herdr-dispatch/bin/dispatch_plugin.py guard \
  --action dispatch_lane --phase yield_and_guard
orchestrator guard: REFUSE dispatch_lane in yield_and_guard
  'dispatch_lane' is not permitted while the orchestrator brain is in 'yield_and_guard'.
  permitted here: harvest, notify_human, read_state, render_board, stall_alarm, status, wait_lanes, wake
# exit 2
```

Two rules cut across the whole table:

- **Probes are refused everywhere.** The whole `probe_*` family, in all seven
  phases, plus a named list. Refusing the *class* rather than judging each case
  removes the decision: a probe whose result arrives is indistinguishable from
  one that justifies acting.
- **The park is a hard stop.** In `yield_and_guard` only wake signals and reads
  pass, and a wake signal must be one of `notify` / `stall_alarm` / `human`. A
  todo reminder is not one.

`--phase` defaults to whatever `ORCHESTRATOR_STATE.json` records, so the gate
polices the brain as it actually is rather than as the caller believes it is.

Like every other gate here, it decides and refuses. It runs no action, never
transitions the brain, and keeps no audit trail of its own — a gate that writes
to the state file to justify itself cannot be trusted to report on it.

## Issue #125 — task contract toolchain clauses

`dispatch.py lint` now also requires a contract to state **how** the work is done
efficiently and **which** standard skill pipeline executes it:

```bash
$PY agent-skills/local/global/dispatch/scripts/dispatch.py lint TASK.md
# Error: Task file 'TASK.md' violates the Issue #125 toolchain contract.
# Missing: 效能准则 (any of: rtk, caveman ultra, codebase-memory-mcp), ...
```

Each clause is an **any-of**, not all-of: demanding every tool turns a contract
check into box-ticking. Contracts predating the issue are grandfathered with
`--allow-legacy`, which warns loudly on stderr rather than passing silently — a
skipped check must never look like a passing one.

**What it does not do:** this is a vocabulary check, not a commitment check. A
contract that merely quotes the term list to explain what the rule requires
satisfies it — observed live, when this repository's own contract passed because
its goal statement enumerates the keywords. Requiring the term to appear in a
directive position would be gameable by rephrasing, so the limit is documented
rather than papered over.

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
                             tests/test_dispatch_prompt_protocol_gate.py \
                             tests/test_install_omp_extensions_local.py -q
```

The prompt gate has a standalone feedback loop:

```bash
python3 scripts/prompt-gate-probe.py   # red-capable: exits 1 until the gate enforces
```