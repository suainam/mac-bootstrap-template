# Agent Subagents

Use subagents for mac-bootstrap work when the task has independent risk lanes.
Keep the main thread responsible for scope, staging, commit selection, and final
publish order.

## Recommended Roles

| Role | Owns | Good tasks | Should not own |
|------|------|------------|----------------|
| Deploy | install and publish flow | dry-run install paths, submodule pointer checks, push-order review | broad debugging |
| Troubleshoot | root-cause analysis | font discovery, launchd logs, shell startup drift, proxy failures | committing or pushing |
| Test | regression gates | `make doctor`, `make check`, `pytest`, CLI smoke checks | code edits |

## Model Defaults

The delegation contract allows only the main tier or the fast tier; pick the
smallest role that still matches risk and never escalate to a costlier tier
without a stated reason. Role names and their tier mapping belong to the host
catalog, not to this document.

| Role | Default tier | Why |
|------|--------------|-----|
| Deploy | fast tier | mostly deterministic git/status/publish checks |
| Test | fast tier | runs fixed commands and reports exact output |
| Troubleshoot | main tier, or fast tier when the evidence is narrow | needs root-cause reasoning across machine state |

Escalate deploy/test only when their findings require design judgment, not just
command execution.

## When To Spawn

The authoritative contract lives in `agent/rules/AGENTS.md` under
`## Subagent Delegation Contract`; this document adds role detail and workflow routing.

Every task text carries the contract fields, including the reporting duty: one
line per milestone and at least every ~60 s, or the parent treats silence as a
defect and intervenes. Liveness is separate from human interruptions: agents
run async while the human coordinates at settled checkpoints.

Concurrency and time caps belong to the authoritative contract above. They
require supported host runtime controls and supervision; prose alone does not
enforce them. Use the stricter host limit and work inline when controls are unavailable.

Acceptance requires substantive live evidence (end-to-end runs, transcripts,
artifacts, or `/create-verification-skill` feature maps). Raw unit test counts
are evidence, but not sufficient alone for live behavior.

After the authoritative size and permission gates pass, possible independent lanes include:

- implementation is still changing while regression checks can run in parallel
- machine state and repo state both need verification
- a fix touches both public `template/` and private parent wrapper
- one agent can do read-only review while another runs live commands

Do not spawn them for tiny single-file edits, when all work depends on the
same mutable file set, or when one agent can finish in about half a day.

## Workflow Pipelines & Skills (P1–P4)

### P1: Verification Skills & Statechart
- `/create-verification-skill`: generate project-local verification skills (`.agents/skills/verify-<app>/`, `.claude/skills/`, `.cursor/skills/`) driving real app behavior from the user's POV with Launch, Doctor, Drive, Evidence, Cleanup sections and feature maps.
- `/maintain-verification-skill`: upkeep loop keeping feature maps honest against source churn.
- `/create-formal-verification-skill` & `/maintain-formal-verification-skill`: formal verification for concurrency races, state machines, or data structure invariants; pairs with `/statechart` for visual rendering.
- Negative control: required only for new or modified verification harnesses or formal properties (demonstrating the check fails on broken code).

### P2: Behavioral Proof & Context Hygiene
- Results tied to requirements, not raw test counts.
- Build deterministic reusable tools only when justified by repeated execution; avoid blanket boilerplate.
- Structural lessons: encode verified traps/decisions into `rules/` or `docs/`.
- Context hygiene: keep context lean; disclose reference details behind pointers.

### P3: Ceremony-Free Vertical Slicing (Matt Skills)
Optional vertical slicing using local skills:
- `/grilling`: Stress-test assumptions and extract hidden constraints into design trees before committing.
- `/to-spec`: Synthesize discussion and codebase state into structured spec without redundant user interviews.
- `/to-tickets`: Decompose spec into context-sized tracer-bullet vertical slices with explicit blocking edges.
- `/implement`: Implement individual slice with TDD at pre-agreed seams.
- `/code-review`: Review diff/branch against repo standards and acceptance criteria.

### P4: Long-Horizon Governance & Decision Records
- Keep scratch decision/evidence/outcome notes during long multi-turn runs; write formal ADR into `docs/adr/` only for durable, surprising architectural choices (no second wiki in `notes/`).
- Adversarial review: reuse `code-review` and `grilling` with skeptic/acceptor dual lenses on critical boundaries and security assumptions.
- Competing designs: compare 2–3 minimal alternatives against explicit criteria before locking in architecture.
- Bespoke playbooks: reserved for multi-subsystem migrations when standard vertical slicing is demonstrably mismatched.
## Prompt Contracts

Deploy subagent:

```text
Verify publish readiness for mac-bootstrap. Do not edit files. Check child
template status, parent status, submodule pointer, privacy gate, and push order.
Report exact commands and blockers.
```

Troubleshoot subagent:

```text
Diagnose the reported runtime issue. Do not edit files unless explicitly asked.
Prove ownership before proposing fixes. Prefer live commands over assumptions.
Report root cause, evidence, and the smallest durable fix.
```

Test subagent:

```text
Run regression checks only. Do not edit files. Use the repo-local environment.
Run make doctor, make check, and focused smoke checks relevant to the change.
Report exit codes, skipped tests, and warnings.
```

## Commit Boundary

Subagents may report findings, but the main thread stages and commits. For the
private-parent/public-template layout:

1. commit and push `template/` first
2. update and commit the parent submodule pointer second
3. keep private overlay changes out of the public template

Do not yield while a child still runs: each one must end as consumed, killed,
or reported lost, and its claims must be verified before they count. The
parent-first ordering above preserves privacy review and avoids publishing a
pointer to a child commit that is not on the remote.
