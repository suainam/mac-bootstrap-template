# Memory Reconcile

Use only when the active platform exposes an Agent memory system and the user requests memory cleanup or the current reconciliation clearly includes it. Follow platform-owned read/write rules; require explicit authorization before changing memory or global Agent configuration.

## Lifecycle

1. Read the memory index and only entries relevant to the current project or change.
2. Verify every retained claim against current authorities.
3. Promote stable knowledge to the correct docs or Agent authority when it explains how the system works, repeatedly recurs, or is needed by the next maintainer.
4. Remove the transient memory entry or reduce it to one pointer after promotion.
5. Delete stale event notes, completed temporary plans, and superseded claims only when their disposition is unambiguous and deletion is authorized.

Keep preferences and cross-project reusable facts in memory. Keep system behavior in docs, Agent-changing constraints in the Agent authority, decisions in ADRs, and event history in version control, issues, changelogs, retrospectives, or archived plans. Do not create a skill as a memory-graduation target.

Measure the platform's loaded index limits when known. If limits are unknown, report size without inventing a threshold. Never bulk-read unrelated memory, copy secrets into reports, or edit machine-generated stores contrary to platform rules.
