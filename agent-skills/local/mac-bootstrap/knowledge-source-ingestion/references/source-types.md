# Source Types

Current target source families:

- `chat_log`
- `meeting_note`
- `mind_map`
- `wiki_page`
- `wiki_pdf`
- `wiki_html`
- `import_doc`

## Adapter contract

Each adapter should expose the equivalent of:

- `supports(path) -> bool`
- `to_blocks(path) -> list[Block]`

Canonical `Block` shape:

```json
{
  "block_type": "paragraph | bullet | heading | topic | table_row | summary",
  "path": ["section", "subsection"],
  "locator": "block:12",
  "text": "raw normalized text",
  "metadata": {}
}
```

## Current repo mapping

- chat logs -> `template/agent/data-hub/scripts/ingest_logs.py`
- `Meetings/*.md` -> markdown meeting adapter
- `Wiki-Clips/*.md` -> markdown wiki adapter
- `Wiki-Clips/*.pdf` -> PDF wiki adapter
- `Wiki-Clips/*.html` -> HTML wiki adapter
- `Mindmaps/*.xmind` -> xmind adapter

## Design guidance

- Markdown meeting notes drift mainly in headings, bullet markers, and transcript style.
- XMind drift mainly in topic-tree depth, inline images, and summary nodes.
- Wiki exports often need a separate adapter because they mix headings, paragraphs, and tables differently from meeting notes.
- Confluence-export PDFs should be treated as their own source family even when they originated from wiki pages.
- Confluence-export HTML should prefer deterministic parsing first: keep headings, bullets, and table rows explicit before considering LLM fallback.

## Date policy

Current default policy is `filename_first`:

- if a file name starts with `YYYY-MM-DD_`, that date is the only valid daily bucket
- otherwise the first landing date in SQLite is valid for the daily bucket
- re-runs should not keep shifting a document into a new day

Optional mode:

- `EXTERNAL_SOURCE_DATE_MODE=filename_only`

If a file can be normalized into blocks with stable boundaries, keep it in deterministic mode.
If boundaries are weak or prose is transcript-like, consider hybrid or LLM fallback mode.
