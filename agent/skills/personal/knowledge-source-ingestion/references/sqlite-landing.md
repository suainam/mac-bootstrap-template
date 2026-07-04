# SQLite Landing

Current priority is SQLite landing, not promotion.

## Current split

- AI chat logs -> `ingest_logs.py` -> `sessions`, `messages`
- External docs -> `ingest_sources.py` -> `source_documents`, `document_chunks`, `extracted_items`

This split is acceptable for now. Do not block SQLite landing on a perfect unified schema.

## Supported source families

- `chat_log`
- `meeting_note`
- `wiki_page`
- `wiki_pdf`
- `mind_map`
- `import_doc` reserved

## Done criteria for this phase

A source family is "landed" when:

1. files or sessions are discoverable
2. records are inserted deterministically into SQLite
3. source counts can be queried
4. sample rows can be inspected without custom one-off code

## Not in scope yet

- ADR/Card generation
- promotion queue
- review packet
- final knowledge materialization
- vector search

Those come later.
