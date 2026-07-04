---
name: knowledge-materialization
description: Promote reviewed knowledge candidates into Daily, ADR, or Card notes after review, keeping candidate_id-based idempotency and SQLite status in sync. Use when candidate review actions are ready and only accepted items should become formal knowledge artifacts.
---

# Knowledge Materialization

Use this skill only after a review packet contains final actions.

## Workflow

1. Confirm the candidate markdown exists for the target date.
2. Run `scripts/run-materialization.sh YYYY-MM-DD`.
3. Read [references/idempotency.md](references/idempotency.md) when verifying duplicate protection.
4. Rebuild the review queue after applying actions so SQLite and markdown stay aligned.
5. Escalate back to review if the candidate type or status is still ambiguous.

## Rules

- Materialize only `accept`.
- Keep Daily promotion marker-based and ADR/Card promotion `candidate_id`-based.
- Preserve `materialized_path` in SQLite for every accepted candidate.
- Re-running the same date must not append duplicate content.
- Do not re-classify claims during promotion.
