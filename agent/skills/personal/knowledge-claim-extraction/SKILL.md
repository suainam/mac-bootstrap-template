---
name: knowledge-claim-extraction
description: Extract typed claim packets from landed source items and chat messages after ingestion, keeping JSON schema output and evidence links for later review. Use when source material has reached SQLite and needs a structured claim layer before candidate generation or promotion.
---

# Knowledge Claim Extraction

Convert landed records into typed claims with evidence pointers.

## Workflow

1. Confirm SQLite landing is current.
2. Run `scripts/run-claim-extraction.sh YYYY-MM-DD`.
3. Read [references/claim-schema.md](references/claim-schema.md) when the caller needs exact packet fields.
4. Keep the output in JSON; do not jump straight to Markdown narrative.
5. Feed the resulting packet into candidate review or later synthesis.

## Rules

- Map deterministic extracted item types directly when possible.
- Keep `fact`, `decision`, `action`, `risk`, `open_loop`, and `insight_candidate` distinct.
- Preserve source and evidence identifiers for every claim.
- Treat chat-derived claims as lower-confidence heuristics unless later validated.
- Do not materialize knowledge in this stage.
