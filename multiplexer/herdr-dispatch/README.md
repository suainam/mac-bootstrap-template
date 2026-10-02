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
| Gate A reflex gate | `lib/orchestrator_guard.py` | judges a tool call at the PreToolUse boundary; whitelist, mechanical, then Jev |
| Gate D semantic watchdog | `lib/watchdog_judge.py` | System One (TypeSafe Jev); autonomous lease extension |
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

A dispatched prompt needs a **resolved opaque Herdr coordinate** (for example
`w3:pB` or `wD:p1` — never `${ORCH_PANE}` or `<orch-pane>`) and a structured
`[NOTIFY]` carrying `DONE:` and `Handoff:` lines.

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
  --handoff "/tmp/handoff/<file>.md" \
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

## The unified dispatch bus

Dispatching a lane was six manual steps — `lint`, `claim`, pane rename,
timestamp, envelope assembly, state flush — and any one could be skipped. The
omissions were invisible until closeout: a lane running with no state entry, a
pane still called `worker-3`, a handoff referenced by a filename nobody minted.

One command now does all of it, in order, atomically:

```bash
python3 bin/dispatch_plugin.py --repo "$PWD" dispatch \
  --task .dispatch/TASK.md --lane-name 1-3-dispatch --target w3:p9
```

| Step | What it does |
|---|---|
| 1 | lane-name convention `^[0-9]+-[0-9]+-[a-z0-9_-]+$`, exit 2 |
| 2 | contract lint (7 sections + Issue #125), exit 1 |
| 3 | claim gate on worktree/branch, exit 2 |
| 4 | mints `YYYYMMDD_HHMMSS` and the handoff path — never typed by hand |
| 5 | assembles the `[DISPATCH]` request with stable identity, callback and handoff |
| 6 | writes the lane to `ORCHESTRATOR_STATE.json`, walks the brain into `yield_and_guard` |
| 7 | delivers through the prompt gate, prints a receipt |

### Parameters are derived, not typed (Issue #136)

The first cut of the bus took six arguments. Five of them were already implied
by the others, and a redundant argument is not a convenience — it is a second
copy that can disagree with the first. `--lane 1-3` beside `--lane-name
1-3-dispatch` is a value that can contradict itself; a `--worktree` pasted from
an earlier run is a value that is stale before it is audited.

| Was | Now | Derived from |
|---|---|---|
| `--lane` | — | the first two segments of `--lane-name` |
| `--highlight` | — | `## 核心成果与证据` in the task, else the first sentence of `## 目标` |
| `--risk` | — | `## 风险与遗留` in the task, else the first line of `## 约束` |
| `--worktree` | — | the target pane's cwd, read from Herdr |
| `--branch` | — | `git -C <cwd> rev-parse --abbrev-ref HEAD` |

The overrides still exist for the case where someone knows better than a probe.
What changed is that they are no longer *required*, and each has a rule:

- **`--lane` is deprecated and never wins.** A value that disagrees with the
  lane name is reported in the receipt and discarded. Honouring it would keep
  the exact inconsistency the merge removes; ignoring it silently would leave
  the caller believing the wrong lane ran.
- **Neither half of the placement may be supplied alone.** `(worktree, "")`
  would reach the claim gate as a lane that claims a directory but no branch —
  the interleaved-commits failure with one leg removed. Supply one and the
  missing half is derived **from the supplied one**, not from the pane: the two
  halves have to describe the same tree, and a branch read from a different
  directory is a claim that looks valid and isolates nothing.
- **A `--branch` that disagrees with the pane's own checkout does not win.** The
  branch in the worktree the lane is actually going to work in is the one worth
  claiming; the disagreement is reported in the receipt rather than applied.
- **Report bullets are overridden, not merged.** A `--highlight` replaces what
  the contract said, so the envelope never carries two sources of the same fact.

### A failed derivation is a refusal, never an empty value

This is the part that matters. Every derived field feeds a gate, and **a gate
fed `""` is a gate that did not run**:

- no worktree and no branch → the claim gate is skipped → two interactive
  agents can share one worktree, which is the failure 1 Lane = 1 Worktree =
  1 Branch exists to prevent;
- no lane id → the state document is keyed under nothing;
- no report bullets → the envelope claims the lane has nothing to say.

So each derivation raises instead of returning a partial value, and a
derivation refusal is **exit 2**, not exit 1. The distinction is actionable: `1`
means "fix your task file", `2` means "fix the world". Reporting a missing pane
as a malformed contract would send an orchestrator to edit a file that is
already correct.

The refusal messages name the cause rather than the symptom:

```text
dispatch: parameter derivation refused the dispatch:
cannot derive the worktree for lane pane w3:p9: Herdr reported no cwd for it.
The pane must exist and have a working directory before its lane can claim one —
dispatching anyway would leave the lane unclaimed and two lanes free to share
a worktree.
```

A **detached HEAD** is refused for the same reason. `rev-parse --abbrev-ref HEAD`
answers the literal string `HEAD` when detached, and claiming a branch named
`HEAD` would look successful while isolating nothing.

Derivation lives in `lib/dispatch_derive.py`, not in `dispatch_bus.py`. That is
not tidiness: the bus holds a hard no-shell invariant (a test asserts `subprocess`
is absent from its source), and both git and Herdr need a subprocess. Splitting
them keeps that invariant testable rather than aspirational — the bus still
never builds a command line, it only asks what the answer is.

### Why atomicity needed a structural change

The contract is: **if any gate refuses, nothing may be renamed, nothing written,
nothing delivered.** That is not achievable by validating inside a sequence of
mutations, because the mutation before the failure already happened.

So the work splits in two:

- `DispatchPlan.plan` is **pure** — it runs every gate, mints the timestamp and
  assembles the envelope, raising before producing a value. A refusal provably
  cannot have mutated anything.
- `DispatchPlan.commit` performs the three mutations in least-observable-first
  order: state, then rename, then delivery. Delivery is last because it is the
  only step the worker can see.

Gates are ordered by cost so one error surfaces per round trip. A malformed lane
name is reported even when the contract is also broken.

Exit codes are deliberately distinct: `1` means "your task file is wrong", `2`
means "this lane is unsafe", `3` means "the lane is half-dispatched". The third
exists because the first two are only true *before* `commit()`; see the exit
table under `/dispatch`.

### Two properties worth knowing

**The parked brain names the lane it waits for.** Parking with the *previous*
wait list instead of the newly dispatched lane produces a brain that believes it
is waiting on nothing while a worker demonstrably runs. Found by a live
self-dispatch, not by reading code — the unit tests passed because the brain
started empty, which hides exactly this bug.

**A brain past the park is refused, not rewound.** If the state machine cannot
reach `yield_and_guard` legally, the bus says so and mutates nothing. Rewinding a
`closed` brain to re-dispatch would quietly discard a finished run.

### Lane naming is enforced, not documented

`research-agy` is refused with exit 2, and the error says why: a bare slug
carries no lane coordinates, so nothing can tell which wave owns it or who is
responsible for it. `handoff_path` re-validates the name, so a nonconforming
lane cannot reach a handoff filename by another route either.

## Ownership boundaries

Writes are partitioned so the short-lived Herdr plugin process and the
long-lived omp extension cannot clobber each other:

| Writer | May write |
|---|---|
| Herdr plugin (`update_lane(writer="plugin")`) | lane `tokens`, `status`, `pane_id`, `agent_name`, `watchdog_verdict`, `watchdog_evaluated_at_unix_ms`, `watchdog_lease_until_unix_ms`, `consecutive_extensions`, `last_seen_seq` |
| omp extension (`update_lane(writer="extension")`) | lane `phase`, `handoff`, `notified_at` |
| omp extension only | Phase 0 (`orchestrator_phase`, `blocked_reason`, `brain`, `active_panes`) |

Crossing a partition raises rather than silently dropping the write.

## Gate D: Zero-Token Semantic Watchdog (Issue #134)

When a child lane is quiet for $\ge$ 3 minutes (measured by monotonic `state_change_seq`),
the semantic watchdog (`lib/watchdog_judge.py`) evaluates whether the lane is engaged in
legitimate heavy computation (e.g. `cargo build`, `pytest`, `npm install`) or is hung:

- **Non-autoregressive classification**: Invokes TypeSafe Jev System One endpoint for typed Noul probabilities, consuming zero conversational tokens.
- **Strict buffer truncation**: Extracts at most the tail 15 lines of sanitized terminal output with ANSI sequences stripped.
- **Dynamic stepped backoff & jitter**: When $P(\text{legitimate}) > 0.70$, automatically extends the watchdog lease with stepped backoff (1st extension: 3m, 2nd: 5m, 3rd+: 10m cap) plus $\pm 15$s random jitter to prevent API thundering herds.
- **Forward progress self-healing**: When `state_change_seq` advances, the consecutive extension counter resets to 0 (next extension returns to 3m baseline).
- **Prompt nudge / abort**: When $P(\text{stalled}) > 0.65$, triggers an automated soft nudge (`\n`) for interactive input prompts or aborts fatal deadlocks.

```bash
# Evaluate a single lane or sweep all awaiting lanes
$PY multiplexer/herdr-dispatch/bin/dispatch_plugin.py watchdog --lane 1-4
$PY multiplexer/herdr-dispatch/bin/dispatch_plugin.py watchdog --sweep
```

Agent **lifecycle** reporting is not in this table on purpose: Herdr's own
`herdr:omp` integration owns it, and
`make dispatch-single-writer-gate` fails the build if dispatch code takes it
over. For the same reason dispatch records an expected resume command but never
attaches one itself.

## Gate A: PreToolUse reflex gate (Issue #133)

The phase whitelist polices *named orchestrator steps*. A tool call is not a
named step, and that gap is how "just checking" turns into child-work takeover:
the orchestrator reaches into a worker's file with `read_file` and never appears
in the action matrix at all. Gate A closes it at the tool boundary, in three
layers ordered by cost — the cheap layer refusing first is the whole design,
because spending a model call to learn that `git reset --hard` is destructive
would be spending tokens on a fact.

| Order | Layer | Decides | Cost |
|---|---|---|---|
| **0** | **Destructive root check** | a destructive command aimed at a canonical root checkout | local, deterministic |
| 1 | Whitelist bypass | `todo`, the state file, the handoffs directory, the orchestrator's own task contract | local, no socket |
| 2 | Mechanical | a business-code read while parked; a probe | local, deterministic |
| 3 | Jev semantics | `is_role_boundary_violation`, `is_illegal_probe_while_parked` (Noul, block > 0.40) | one batched call, or offline heuristics |

**The destructive check runs before the bypass, and that ordering is the whole
point.** The whitelist is a bypass, and a bypass placed ahead of a mechanical
rule swallows it: `cat handoffs/x.md && git reset --hard` is a management read
followed by the destruction of a root checkout, and reading the leading path
first waves the entire line through. Every layer is individually correct, so no
per-layer test catches this — only the composition does.
`is_management_call` disqualifies destructive text as a second, redundant
defence, so the property survives either mechanism being removed.

```bash
# Judge one tool call; exits 2 on a refusal
$PY multiplexer/herdr-dispatch/bin/dispatch_plugin.py gate \
    --phase yield_and_guard --tool read_file --target .worktrees/1-4/src/app.py
```

`--phase` defaults to whatever the state file records, for the same reason the
`guard` command does: the gate polices the brain as it is, not as the caller
believes it to be. `--offline` skips layer 3 entirely.

### Root checkout protection

Destructive commands — `git reset --hard`, `git clean -fd`, `git checkout -- .`,
`git push --force`, `rm -rf`, `git branch -D` — are refused **in every phase**
unless the working directory is an isolated lane worktree.

This is an incident written down. In a canonical root checkout the working tree
is the *only* copy of whatever is uncommitted there, so a reset there loses work
that no lane can restore and no other branch holds. The park is not the only
thing that should have prevented it, which is why this rule is phase-independent
rather than folded into the `yield_and_guard` checks.

The destructive set is deliberately wider than the two commands from the report:
a gate drawn at exactly the commands that have already fired is a gate one flag
away from failing again. Read-only `git` is unaffected — the incident was about
destroying a tree, not reading one — and neither are `--soft` or `--mixed`
resets, which keep the working tree.

Two details are easy to get wrong, and both have tests:

- **The rule is not gated on the tool class.** A destructive command is a fact
  about the *command*; naming a tool this gate has not heard of must not silence
  it. Only the probe rule consults the tool name, because "is this a probe" is a
  question about a command line and the tool name is the only signal that the
  input is one.
- **The path is normalised before the segment check.** A substring test on the
  raw string admits `<root>/.worktrees/../<root>` — the root checkout wearing a
  worktree's name. Normalisation is lexical rather than filesystem-resolving, so
  a lane worktree that has not been created yet is still permitted.

Isolation is judged from every directory the command could act on, not only the
cwd: `git -C <root> clean -fd` run from a lane worktree is a root checkout
reached through the back door, and the checks are a conjunction so one named
root is enough to refuse.

**The same reasoning governs the whitelist.** Its markers are a substring list, so
the path is normalised before the comparison — otherwise
`.dispatch/../src/app.py` contains the marker and the whitelist vouches for a
read of a lane's source. For the same reason the parked source rule keys on the
*path* rather than the tool name: renaming `read_file` to `read` would otherwise
turn the rule off with no other symptom.

### What this gate is not

It matches commands **as text** and never parses a shell, so `sh -c` with an
encoded payload, a script file, or an alias is outside what it can see. Matching
the text does catch `&&` chaining, subshells and `xargs` as substrings, which
covers most of the realistic accidental cases. And it is not a sandbox: it
refuses what it recognises, it cannot stop a process that already started. The
boundary it enforces is the orchestrator's own tool calls, which is where the
incident happened.

The Jev endpoint comes from `TYPESAFE_API_URL` and the bearer token from
`TYPESAFE_API_KEY` — both the operator's own environment, and the same trust
boundary `handoff_judge.py` and `watchdog_judge.py` already use. A misconfigured
`TYPESAFE_API_URL` would send the key elsewhere; restricting it would be a change
to all three gates, not to this one.

An endpoint answer that cannot be read — `"high"`, `null`, a missing question, a
`NaN`, a value outside `[0, 1]` — is **no answer**, not a zero. `_noul` returns
`(value, usable)` and the caller falls back to the heuristics, because collapsing
"unusable" into `0.0` is the one direction a gate must never fail in: `0.0` is
indistinguishable from the model being confident there is no violation. The
model name the endpoint reports is sanitised to a single short token before it
reaches a report, a steer or a log.

### The `cwd` dependency

Isolation is judged from a working directory, and a tool event does not carry
one. `index.ts` therefore forwards the session's `cwd` from the handler context —
the same place `session_start` reads it from. If it were dropped, every
destructive command would look like it runs in a root checkout and none would be
allowed: correct, but it would also refuse a lane resetting its own worktree, and
a gate that refuses correct work is one people route around. Both directions are
pinned by tests, using the context shape a real host produces.

**Isolation roots, and one deviation.** The rule accepts `.worktrees/`,
`.herdr/worktrees/`, and `worktrees/`. The issue text named only
`.herdr/worktrees/`; the other two are this repository's own established lane
locations (`agent/rules/adversarial-review-gate.md` mandates `.worktrees/<name>`),
and a boundary that refused them would refuse the lanes it exists to protect. The
deviation is recorded here rather than left implicit.

### Why a refusal injects a steer

A block that only says "no" leaves the model to pick a replacement, and the
cheapest replacement is the behaviour just refused. So every refusal carries a
corrective steer naming the legal next action — wait for worker IPC, or use a
lane worktree for destructive commands — delivered to the session as an `aside`.

### Two halves, one policy

`lib/orchestrator_guard.py` is the authority; `reflex.ts` is the in-process fast
path that runs before it, so the in-session block needs no subprocess. Each rule
appears in both, and `tests/dispatch-reflex.test.ts` asserts they still agree —
constant sets textually, and every classifier behaviourally by running one
corpus through the real Python module and requiring identical answers. A rule
added on one side only shows up there as a disagreement rather than as a hole in
the seam. That behavioural half earned its place: it is what caught a
case-folding bug that turned every handoff and task contract ending in `.py`
into a business-code read in the fast path while the authority whitelisted it.

## `/dispatch` — the global slash command (Issue #137)

Inside an omp session, the bus is one command away:

```
/dispatch --task .dispatch/TASK.md --lane-name 1-3-dispatch --target w3:p9
```

It is registered by the same extension that runs the brain loop, which is
already linked into `$PI_CODING_AGENT_DIR/extensions/` — so it is global and
needs no per-project installation.

**Why a slash command rather than a skill.** The host parses the arguments, so
they reach the bus as an argv array handed to `spawnSync` with `shell: false`.
There is no string for a quote to escape into: a path with a space in it works,
and the literal `'\n'` that produced the one-line-report defect cannot survive.
That defect and this command are the same problem seen from two sides — one
fixed the *text*, this removes the *hand-quoting*.

**The command holds no gates.** It translates arguments into argv and nothing
else; lint, claim, lane naming, atomicity and the exit codes all stay in
`dispatch_plugin.py`. This is load-bearing rather than tidy: the exit codes are
a contract an orchestrator programs against, and a second implementation would
eventually disagree with the first about which code a given refusal produces.

So the codes pass through unchanged, with the bus's own stderr intact — the bus
names the *colliding lane*, and paraphrasing that would send the orchestrator
looking somewhere other than where the collision is:

| Exit | Meaning | What to do |
|---|---|---|
| `0` | dispatched; the receipt shows what was derived | — |
| `1` | the task contract is malformed | fix the contract file |
| `2` | a rule refused: bad lane name, worktree collision, failed derivation | fix the lane or the pane — **nothing was renamed, written or delivered** |
| `3` | delivery outcome was not confirmed *after* the plan committed | see below |

Exit `3` exists because "a rule refused, nothing happened" stops being true once
`commit()` has run. A prompt submission may fail after bytes were accepted or
while confirmation is in flight, so a transport error is **not proof that
nothing was sent**.

The lane records `delivery_status: unknown`, keeps the same `run_id`,
`dispatch_id`, physical claim and handoff, and does not mint a replacement task.
Re-running the same dispatch command is an idempotent delivery retry: the bus
reuses the existing timestamp, signature and handoff after verifying that the
task, worker pane and parent callback identity did not change. A host response
that explicitly rejects input before acceptance is recorded separately as a
known rejection.

A killed bus (signal, no exit status) is also not reported as a refusal: nothing
is knowable about a process that died mid-flight, so the honest answer is "check
the state before retrying".

The bus is located by walking up from the working directory and also recognizes
a parent checkout whose public template lives under `template/`, so `/dispatch`
works from both template worktrees and the parent repository. `HERDR_DISPATCH_PLUGIN`
overrides the search for a fork or unusual layout, and `HERDR_DISPATCH_PYTHON`
selects the interpreter.

### The derived signature has to be attributable

The bus parks the brain on **lane ids** (`awaiting_lanes` holds `1-3`), so a
report has to name one. `notify.laneFromSignature` reads the signature's leading
token and `consumeNotify` drops the park entry for whichever lane that resolves
to — so a signature naming a *different* lane leaves `awaiting_lanes` untouched
and the orchestrator re-nudges forever against a lane that demonstrably
reported.

`--signature` is therefore **reconciled against the lane, not honoured**. The
invariant is narrow: the leading token is the lane id, and everything after it
is free-form. Three cases:

| supplied | result |
|---|---|
| empty | adopted as `<lane>_<pane>` |
| already names this lane | kept verbatim, suffix and all |
| names a different lane | rewritten to `<lane>_<pane>`, with a receipt note |

That last row is the one that used to deadlock. `w3:p9_opencode_mac-bootstrap`
— the form the dispatch SKILL.md used to recommend — names a *pane*, not a lane,
so a worker reporting with it resolved to a lane the brain was not waiting on.

Reconciliation owns the prefix only, because there is no safe alternative:
honouring the caller's signature keeps the divergence, and guessing wrong costs
a permanent deadlock rather than a wrong label.

`signature_lane` (Python) and `laneFromSignature` (TypeScript) are two
implementations of one rule split across the language boundary. Both are
asserted against **one shared table** in
`tests/test_dispatch_param_derivation.py` and `tests/dispatch-slash.test.ts`,
which is what keeps the copy honest.

`tests/dispatch-e2e.test.ts` runs the whole round trip — dispatch, read the
delivered text, feed it back to the extension — because each half is separately
correct and they can still fail to meet.

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
                             tests/test_dispatch_semantic_watchdog.py \
                             tests/test_dispatch_bus.py \
                             tests/test_dispatch_param_derivation.py \
                             tests/test_install_omp_extensions_local.py -q
make dispatch-test     # bun: brain, notify, ledger, governance, slash, e2e
```

The prompt gate has a standalone feedback loop:

```bash
python3 scripts/prompt-gate-probe.py   # red-capable: exits 1 until the gate enforces
```