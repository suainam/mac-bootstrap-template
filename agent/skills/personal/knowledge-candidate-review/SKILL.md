---
name: knowledge-candidate-review
description: Build and refresh machine-readable candidate review queues from extracted claims or items, preserving review status and writing the review projection into Obsidian. Use when the workflow needs a daily review packet before any accepted knowledge is promoted.
---

# Knowledge Candidate Review

Use this skill to maintain the pre-promotion review layer.

## Workflow

1. Ensure ingestion and claim extraction are current for the target date.
2. Run `scripts/run-candidate-review.sh YYYY-MM-DD`.
3. Inspect the generated candidate markdown and keep review actions lightweight.
4. Read [references/review-boundary.md](references/review-boundary.md) when deciding what belongs in this layer.
5. Hand off to `knowledge-materialization` only after review actions are set.

## Rules

- Keep SQLite `knowledge_candidates.status` as the source of truth.
- Treat the markdown file as a re-buildable review projection.
- Preserve stable `candidate_id` values across re-runs.
- Do not auto-accept candidates here.
- Prune orphan candidates when their backing source rows disappear.
