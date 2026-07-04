---
name: knowledge-hygiene-audit
description: Audit the knowledge lifecycle ledger for orphan candidates, stale reviews, duplicate promoted knowledge, date attribution drift, and broken materialization links. Use when running weekly hygiene, validating idempotency, or checking whether the knowledge system can be trusted before further automation.
---

# Knowledge Hygiene Audit

Use this skill to inspect ledger health and produce concrete repair actions.

## Workflow

1. Choose the stale cutoff date for the audit window.
2. Run `scripts/run-hygiene-audit.sh --stale-before YYYY-MM-DD`.
3. Read [references/audit-checks.md](references/audit-checks.md) when you need the exact checks.
4. Review the report before mutating any records.
5. Apply fixes in the owning stage, not inside the audit itself.

## Rules

- Report on the ledger and vault together.
- Prefer deterministic checks over heuristic prose.
- Surface broken mappings and duplicate promoted knowledge explicitly.
- Keep the audit read-only.
- Use the output as the weekly hygiene gate before new promotion waves.
