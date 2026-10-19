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
`## Subagent Delegation Contract`; this document only adds role detail.

Every task text carries the contract fields, including the reporting duty: one
line per milestone and at least every ~60 s, or the parent treats silence as a
defect and intervenes. The examples below are the role-specific body; wrap them
with Outcome, Boundaries, Verification and Stop/Pause from the contract.

The caps (5 concurrent children, 5 minutes wall clock each) are a contract the
host must configure: OMP defaults to 32 concurrent children with no wall clock,
so an unconfigured host lets a silent child run for minutes. The machine-local
values live in the private overlay, not in this template.

Spawn subagents when at least two lanes can run independently:

- implementation is still changing while regression checks can run in parallel
- machine state and repo state both need verification
- a fix touches both public `template/` and private parent wrapper
- one agent can do read-only review while another runs live commands

Do not spawn them for tiny single-file edits, when all work depends on the
same mutable file set, or when one agent can finish in about half a day.

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
