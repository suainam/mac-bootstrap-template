# Audit Report

The bundled audit is a deterministic lead generator, not a semantic judge.

- `error`: broken mechanical contract; strict mode fails.
- `warning`: routing budget or other actionable risk; strict mode fails.
- `candidate`: possible semantic duplication; inspect authority and audience before editing.
- `safe-auto-repair`: target is mechanically unambiguous.
- `review-required`: meaning, ownership, or compatibility requires judgment.

Measurements cover tracked and unignored active Markdown. Archives, artifacts, dependencies, worktrees, and ignored files are excluded. Persistent limits are total lines, estimated tokens, and bytes emitted in `budgets`; use the report values rather than restating thresholds.

Exit zero means mechanical gates passed. It does not prove every candidate should be removed or that the handbook improves Agent performance; use [evaluation.md](evaluation.md) for that claim.
