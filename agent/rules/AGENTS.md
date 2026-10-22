## Core Operating Rules

These rules apply to every task in this project unless explicitly overridden.
Bias: caution over speed on non-trivial work. Use judgment on trivial tasks.

### Occam Gate — before design

Apply `ponytail` before design: choose the smallest existing path that satisfies
the request. Add abstractions, dependencies, agents, or files only when needed.

### Rule 1 — Think Before Coding
State assumptions explicitly. If uncertain, ask rather than guess.
Present multiple interpretations when ambiguity exists.
Push back when a simpler approach exists.
Stop when confused. Name what's unclear.

### Rule 2 — Surgical Changes
Touch only what you must. Clean up only your own mess.
Don't "improve" adjacent code, comments, or formatting.
Don't refactor what isn't broken. Match existing style.

### Rule 3 — Goal-Driven Execution
Define success criteria. Loop until verified.
Don't follow steps. Define success and iterate.
Strong success criteria let you loop independently.

### Rule 4 — Use the model only for judgment calls
Use me for: classification, drafting, summarization, extraction.
Do NOT use me for: routing, retries, deterministic transforms.
If code can answer, code answers.

### Rule 5 — Generated-token budgets
Budget counts provider-reported generated output, including reasoning when already
included in output; never add reasoning twice. Input and cache reads are separate.
Default: 4,000 per user task; 30,000 per session, including delegated work.
Follow-ups and compaction do not reset usage. Only an explicit new task resets the
task counter; session usage remains. The host warns at 80% and pauses further
requests/spawns at the limit; missing usage is incomplete, not zero. Resume requires
an explicit operator allowance. Report unsupported enforcement; prose is no hard cap.
OMP mechanics and limitations: `docs/agent-runtime-guardrails.md` in the template.

### Rule 6 — Surface conflicts, don't average them
If two patterns contradict, pick one (more recent / more tested).
Explain why. Flag the other for cleanup.
Don't blend conflicting patterns.

### Rule 7 — Read before you write
Before adding code, read exports, immediate callers, shared utilities.
"Looks orthogonal" is dangerous. If unsure why code is structured a way, ask.
When the user names a skill that is absent from the exposed catalog, check the
exact installed paths under `~/.codex/skills`, `~/.agents/skills`, and
`~/.claude/skills`, following symlinks, before declaring it unavailable.

### Rule 8 — Tests verify intent, not just behavior
Tests must encode WHY behavior matters, not just WHAT it does.
A test that can't fail when business logic changes is wrong.

### Rule 9 — Checkpoint after every significant step
Summarize what was done, what's verified, what's left.
Don't continue from a state you can't describe back.
If you lose track, stop and restate.

### Rule 10 — Fail loud
"Completed" is wrong if anything was skipped silently.
"Tests pass" is wrong if any were skipped.
Default to surfacing uncertainty, not hiding it.

### Rule 11 — Credentials and browser ownership
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

### 1. Structural Code Discovery (CBM via `xd://`)
- CBM MCP tools are mounted as `xd://` devices (e.g. `xd://mcp__codebase_memory_mcp_search_graph`, `xd://mcp__codebase_memory_mcp_trace_path`). Execute via `write(path="xd://...", content='{...}')`.
- **Mandatory Routing**: MUST use CBM first for symbols, functions, classes, methods, routes, callers/callees, blast radius, and architecture overview.
- **Prohibition**: Do NOT use `glob` or `read` on multiple code files to discover symbols or trace dependencies before running `search_graph` or `trace_path`.
- **Threshold**: If a search or glob would return >20 code files, abort and use CBM graph queries.
- **Coverage**: Call `check_index_coverage` before stating absence or dead code.

### 2. Multi-Tier Agent Memory
- **SSOT Layers**:
  1. **Codebase-Memory (CBM)**: Deterministic code architecture (`xd://mcp__codebase_memory_mcp_*`).
  2. **Shared memory MCP**: Long-term semantic decisions, architectural trade-offs, and operational pitfalls. Use the tools the host actually mounts (on OMP: `memory_query`, `memory_read_page`, `memory_recent`, `memory_write_page`); there is no `remember`/`recall`.
  3. **Local Runtime (`agent.db`)**: Ephemeral turn context and session compaction.
- **Practice**: Query shared memory before a non-trivial refactor or debug in a subsystem with history, and read the full page on a hit. Record a durable trap only after live verification. A missing memory tool is a defect, not permission to invent history. Code in the repository is the ultimate ground truth.

## Subagent Delegation Contract

Spawn only for ≥2 independent slices or read-only scouting that saves main context. Otherwise work inline (Occam Gate wins). Task size gate: work a single agent can finish in about half a day stays inline; only week-scale work with shifting conditions earns orchestration.

- **Caps**: ≤5 concurrent subagents; ≤5 min wall-clock each. The host must enforce both (`task.maxConcurrency`, `task.maxRuntimeMs` in OMP; defaults are 32 and unlimited). Models: main tier or fast tier only; never a costlier tier.
- **Coordinator**: the parent owns scope, slice design, staging, and the final report; it does not implement slices itself. Keep its context on goals and evidence, not implementation detail.
- **Preflight before spawn**: write the slice list, each slice's files, the verification command, and the human gates the work will cross. Surface missing access, credentials, or decisions now; do not discover them mid-run.
- **Task contract** (the `task` text MUST carry all of it, goal-style; use `qiaomu-goal-meta-skill` when the slice is unclear):
  - Outcome: one concrete result, not an activity.
  - Boundaries: exact files/dirs it may read or write; read-only unless a single named writer.
  - Verification: command or artifact that proves done.
  - Stop when: proof of completion. Pause if: credential, destructive step, or product decision needed.
  - Rationale: for non-obvious choices, report options considered, the choice, and the evidence behind it.
  - Time: 5 min cap. Report one-line progress to the parent at each milestone and at least every ~60 s; silence is a defect.
- **Non-blocking questions are recorded, not asked**: keep working on the parts that are already clear, batch the decisions for the next human gate, and stop only for genuinely blocking gates (merge, credentials, destructive actions).
- **Parent supervision**: run subagents as async jobs and stay quiet while they work. Patrol every child once at ~3 min via `history://<id>`: on track → leave; drifting → steer with `write agent://<id>`; stuck, silent, or off-scope → `write proc://<id>/kill`, keep its partial output, and take over or respawn narrower.
- **Closeout**: never yield with a running child. Each child ends as consumed, killed, or reported lost. Verify its claims before relying on them. If the session spanned ≥3 verification rounds or produced a wrong call, run `retro` and write at least one lesson back to `rules/` or `docs/`.

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
