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

Use the smallest model that matches risk:

| Role | Default model | Why |
|------|---------------|-----|
| Deploy | `gpt-5.4 medium` | mostly deterministic git/status/publish checks |
| Test | `gpt-5.4 medium` or mini | runs fixed commands and reports exact output |
| Troubleshoot | `gpt-5.5 medium` | needs stronger root-cause reasoning across machine state |

Escalate deploy/test only when their findings require design judgment, not just
command execution.

## When To Spawn

Spawn subagents when at least two lanes can run independently:

- implementation is still changing while regression checks can run in parallel
- machine state and repo state both need verification
- a fix touches both public `template/` and private parent wrapper
- one agent can do read-only review while another runs live commands

Do not spawn them for tiny single-file edits or when all work depends on the
same mutable file set.

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

This preserves privacy review and avoids publishing a parent pointer to a child
commit that is not on the remote.
