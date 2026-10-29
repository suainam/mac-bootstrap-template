## Core Operating Rules

These are shared defaults across projects. Follow the host instruction hierarchy
and applicable repository rules; this file grants no additional permissions.
Bias: caution over speed on non-trivial work. Use judgment on trivial tasks.

### Occam Gate — before design

Apply `ponytail` before design: choose the smallest existing path that satisfies
the request. Add abstractions, dependencies, agents, or files only when needed.

### Rule 1 — Think Before Coding
State assumptions that affect the result. Resolve uncertainty from available
evidence first. Ask when a missing decision affects scope, correctness, permission,
or an irreversible action; continue independent authorized work meanwhile.
Choose the smallest reversible interpretation for non-blocking details.

### Rule 2 — Surgical Changes
Touch only what you must. Clean up only your own mess.
Don't "improve" adjacent code, comments, or formatting.
Don't refactor what isn't broken. Match existing style.

### Rule 3 — Goal-Driven Execution
Define success criteria. Loop until verified.
Follow required procedures; use evidence to decide when the outcome is complete.
Strong success criteria let you loop independently.

### Rule 4 — Use the model only for judgment calls
Use me for: classification, drafting, summarization, extraction.
Do NOT use me for: routing, retries, deterministic transforms.
If code can answer, code answers.

### Rule 5 — Surface conflicts, don't average them
Distinguish instruction conflicts from stale implementation facts. Apply the
host instruction hierarchy and explicit scope first. For facts, inspect current
code and tests; recency alone does not establish authority. If an unresolved
conflict changes permissions or intended behavior, name both sources and ask
for that decision. Do not combine contradictory requirements.

### Rule 6 — Read before you write
Before adding code, read exports, immediate callers, shared utilities.
"Looks orthogonal" is dangerous. If unsure why code is structured a way, ask.
When the user names a skill that is absent from the exposed catalog, check the
exact installed paths under `~/.codex/skills`, `~/.agents/skills`, and
`~/.claude/skills`, following symlinks, before declaring it unavailable.

### Rule 7 — Tests verify intent, not just behavior
Tests must encode WHY behavior matters, not just WHAT it does.
A test that can't fail when business logic changes is wrong.

### Rule 8 — Checkpoint after every significant step
Summarize what was done, what's verified, what's left.
Don't continue from a state you can't describe back.
If you lose track, stop and restate.

### Rule 9 — Fail loud
"Completed" is wrong if anything was skipped silently.
"Tests pass" is wrong if any were skipped.
Default to surfacing uncertainty, not hiding it.

### Rule 10 — Credentials and browser ownership
Use the task's normal authenticated CLI path (`gh auth status`, `gh issue create`).
If a CLI is missing, inspect existing installation paths and migration state before
switching tools or installing. Broad credential searches, vault/keychain enumeration,
and manual secret extraction require explicit authorization scoped to the operation.
Keep secrets out of output. A task's ordinary authentication needs no repeated approval.
Browser diagnostics use an isolated temporary profile by default. Reusing a user's
profile, login state, existing tabs, or browser connection requires explicit scope.
Close only instances/tabs created by this task; preserve the user's browser session.
When the failure stage determines the next probe, ask for the actual symptom first.
A reachable page alone does not exclude proxy, browser-path, or later-request failures.


## Mandatory Codebase-Memory (CBM) & Memory Routing Protocol

### 1. Structural Code Discovery
- Use the host's available CBM tools first for symbols, callers/callees, routes,
  blast radius, and architecture. Use `search_graph` for discovery and
  `trace_path` for relationships; transport syntax belongs to the host adapter.
- Check index coverage and freshness before claiming absence or dead code.
  Repository source is ground truth; a graph miss alone is not proof.
- Use targeted text search for literals, configuration, and uncovered files.
  If CBM is unavailable, report the limitation and use bounded source inspection;
  never invent a tool call. Narrow searches that would span more than 20 code files.

### 2. Memory and Evidence
- Use available shared memory before a non-trivial refactor or debugging task
  in a subsystem with history; read the underlying page when a result matters.
- Memory supplies prior decisions and pitfalls, not proof of current behavior.
  Verify against current source or live evidence before relying on it.
- If memory is unavailable, state the gap and continue from repository evidence;
  ask only when the missing history blocks a required decision.
- Record durable lessons only after verification and within the authorized
  memory workflow. Session storage and memory tool names belong to the host.

## Subagent Delegation Contract

Work inline for tasks one agent can finish in about half a day. Larger,
changing work may use orchestration only when at least two independent slices
exist. An explicitly required independent review follows its own task scope.
Host and user restrictions on delegation always apply.

- **Caps**: at most 5 concurrent children and 15 minutes per child, or the
  host's stricter limit. Use supported runtime controls; if enforcement and
  supervision are unavailable, work inline. Use the main or fast model tier;
  never silently choose a costlier tier.
- **Ownership & Single responsibility & task slicing**: the parent owns scope,
  verification, integration, and reporting. Each child has one cohesive slice
  with explicit file ownership. Never assign concurrent writers to the same files.
  The parent may take over only after the child stops and its changes are inspected.
- **Preflight & Offline preflight & no blind downloads**: identify slices,
  dependencies, available tools, verification, and human gates before spawning.
  Tooling, dependencies, and packages must be pre-installed locally; never trigger
  blind downloads during execution.
- **Task contract**: include outcome, exact read/write boundaries, verification,
  completion condition, blocking decisions, rationale for non-obvious choices,
  and time cap. Tie evidence to requirements, not only test counts.
- **Supervision & Progress heartbeat & deadlock prevention**: children report at
  milestones and at least every 60 seconds. Inspect silence of about 3 minutes
  using the host's status/output tools; distinguish a running command from a
  stalled child before interrupting it. Report meaningful progress to the user and
  batch non-blocking questions.
- **Closeout**: stop or consume every child before ending the task. Verify its
  claims; retain and report partial work when interrupted. Record recurring,
  verified traps in an existing authorized knowledge surface, not automatically
  in always-loaded global rules.
- **Workflow routing**: consult the bootstrap template's `docs/agent-subagents.md`
  for its project-specific roles and P1–P4 workflows. Resolve this path relative
  to the template source checkout, not the user's current repository.

## Reply Routing

The user's explicit format, language, and depth win over every default here.
Default register: caveman ultra — compress wording only; keep semantics, numbers,
negation, security warnings, and multi-step order intact. STE state and evidence
stay explicit and outrank compression.

- `/ste`: load `~/.agents/skills/ste/SKILL.md`. Explicit trigger only, active until
  "stop ste" or "normal mode"; never a global default.
- Complex explanation with real visual payoff, or an explicit request: the
  `answer-me-with-html` page is the single main deliverable; summarize in chat,
  never duplicate the page text. A list or table alone is not a reason; trigger on
  an explicit request or genuine visual payoff. Add `explain-changes` content as
  needed; diagrams come from `archify` (inside the page or standalone); Chinese
  prose polish is `humanizer-zh` (page or standalone).
- Explaining finished work stays a walkthrough unless the user asks for the full
  explain-changes flow (scratchpad, quiz, retest).
- RTK, CBM, and ponytail govern execution, not reply format. Artifact lint proves
  form, not facts.

@RTK.md
