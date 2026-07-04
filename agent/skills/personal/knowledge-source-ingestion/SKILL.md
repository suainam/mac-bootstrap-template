---
name: knowledge-source-ingestion
description: Use when landing AI chat logs, meeting notes, wiki exports, mind maps, or imported docs into SQLite for the Agent Data Hub, or when extraction quality drifts and source adapters or schemas need adjustment.
---

# Knowledge Source Ingestion

Turn external source files into stable `blocks`, then into typed extracted items.

This skill is stage 2 in the 2.0 lifecycle and currently optimizes for one outcome:

- get every supported source family into SQLite without dropping structure
- generate a lightweight candidate-review queue and optionally materialize reviewed items into Obsidian

Sibling skills in the lifecycle:

- `knowledge-reuse-retrieval` for preflight search
- `knowledge-claim-extraction` for the typed claim layer
- `knowledge-candidate-review` for review queue maintenance
- `knowledge-materialization` for accepted promotion
- `knowledge-daily-weekly-synthesis` for narrative summary
- `knowledge-hygiene-audit` for weekly health checks

Repo touchpoints:

- `template/agent/data-hub/ingest_logs.py`
- `template/agent/data-hub/ingest_sources.py`
- `template/agent/data-hub/source_adapters/`
- `template/agent/data-hub/source_ingest_store.py`
- `template/agent/data-hub/schema.sql`
- `template/agent/data-hub/daily_summary.py`

## Workflow

1. Identify the source family and the real sample files.
Completion criterion: you know whether the request is about AI chat logs, meeting notes, wiki exports, mind maps, or import docs.

2. Read [references/source-types.md](references/source-types.md) and choose the adapter path.
Completion criterion: you know whether to use `ingest_logs.py`, `ingest_sources.py`, or add a new source adapter.

3. Normalize the source into canonical `Block` objects before classification.
Completion criterion: non-chat source structure is expressed as stable blocks with locators and metadata.

4. Read [references/extraction-schema.md](references/extraction-schema.md) and map blocks into typed extracted items.
Completion criterion: extracted items have correct type boundaries and trace back to document and chunk or session/message.

5. First finish SQLite landing. Do not start promotion, review, or knowledge materialization work unless explicitly asked.
Completion criterion: the source is queryable in SQLite through the correct tables.

6. Use deterministic parsing first; only use LLM fallback when structure is too weak for stable rules.
Completion criterion: parser changes live in adapters or shared classification rules, not in ad hoc prompt hacks.

7. Re-run ingestion on real samples and inspect outputs.
Completion criterion: SQLite rows match the source intent, not just the expected row count.

8. Read [references/review-rules.md](references/review-rules.md) when candidate generation or materialization work begins.
Completion criterion: review actions remain lightweight and traceable, and accepted items are the only ones materialized.

## Rules

- Keep format parsing separate from business classification.
- Keep orchestration separate from adapter parsing and separate from SQLite persistence.
- Do not force one parser to absorb unrelated source formats.
- Keep AI chat ingestion separate from document-style source ingestion.
- Keep `summary`, `decision`, `action`, `risk`, `open_loop`, `topic`, and `fact` distinct unless a source truly lacks the distinction.
- Prefer fixing drift at the lowest broken layer: block boundaries first, classification second, LLM fallback last.
- Preserve traceability for every extracted item.
- For this phase, SQLite completeness matters more than downstream elegance.
- Candidate review files must stay machine-readable by script and easy for humans to edit.
- Only reviewed `accept` items should materialize into `10_Periodic/Daily` or `40_Knowledge/*`.

## References

- Adapter and source-family guidance: [references/source-types.md](references/source-types.md)
- Canonical extracted item schema: [references/extraction-schema.md](references/extraction-schema.md)
- Candidate and promotion boundary: [references/review-rules.md](references/review-rules.md)
- Example tasks and expected usage: [references/examples.md](references/examples.md)
- SQLite landing scope and boundaries: [references/sqlite-landing.md](references/sqlite-landing.md)

## Scripts

- Run the standard ingest verification loop with `bash .agents/skills/knowledge-source-ingestion/scripts/check-ingestion.sh`
- Run chat + source SQLite landing with `bash .agents/skills/knowledge-source-ingestion/scripts/run-sqlite-landing.sh`
- Run the full cycle with `bash .agents/skills/knowledge-source-ingestion/scripts/run-full-cycle.sh "$HOME/work/config/mac-bootstrap" 2026-07-04`
