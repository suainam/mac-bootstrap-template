# Audit Report

The bundled audit is a deterministic lead generator, not a semantic judge.

- `error`: broken mechanical contract; strict mode fails.
- `warning`: routing budget or other actionable risk; strict mode fails.
- `candidate`: possible semantic duplication; inspect authority and audience before editing.
- `safe-auto-repair`: target is mechanically unambiguous.
- `review-required`: meaning, ownership, or compatibility requires judgment.

Measurements cover tracked and unignored active Markdown. Archives, artifacts, dependencies, worktrees, and ignored files are excluded. Persistent limits are total lines, estimated tokens, and bytes emitted in `budgets`; use the report values rather than restating thresholds.

`UNREADABLE_MARKDOWN` identifies a file whose measurement, link, and duplication checks were skipped because reading or UTF-8 decoding failed. `ENCRYPTED_MARKDOWN` identifies a TSD-wrapped file on disk. Materialize it to an external temporary path with `$decrypt-materialize`, preserve the source, retain its verified JSON result, and rerun with `--materialized-manifest <result.json>`; the audit then checks the materialized bytes while reporting the logical source path. Missing, stale, mismatched, in-tree, or unverified manifests remain strict errors. Other readable files are still checked. Do not silently transcode or treat either file as reviewed. Explicitly scoped ignored projections and legacy directories require the separate coverage ledger; this script does not establish their completeness.

Exit zero means mechanical gates passed. It does not prove every candidate should be removed or that the handbook improves Agent performance; use [evaluation.md](evaluation.md) for that claim.
