# Idempotency Rules

- Daily notes rely on `<!-- knowledge_candidate:<candidate_id> -->`.
- ADR and Card notes rely on frontmatter `candidate_id`.
- `materialized_path` in SQLite must point back to the note that was created.
- A repeat run may refresh status and regenerate the review view, but it must not duplicate note content.
