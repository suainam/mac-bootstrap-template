---
name: knowledge-record
description: |
  Record trusted live-agent knowledge directly into SQLite knowledge_records. Owns the record contract for ADR, Card, and Daily entries in mac-bootstrap data-hub, including suggest-first drafting, field expectations, examples, and the push-path writer implementation.
scope: project
triggers:
  - "knowledge record"
  - "record knowledge"
  - "记录知识"
  - "生成知识记录"
  - "suggest knowledge record"
  - "write knowledge record"
  - "push knowledge to sqlite"
---

# Agent Usage Contract

When recording the current conversation, the agent should not ask the human to
manually provide transcript data. The agent must synthesize the active thread
into `--thread-summary` or pass structured `--thread-json` when invoking
`scripts/record_knowledge.py suggest`.

Prefer `--thread-summary` for normal agent calls because it is compact, avoids
leaking irrelevant conversation details, and keeps the strict writer focused on
recordable knowledge. Use `--thread-json` only when the exact turn structure is
needed for diagnosis.

After saving, show the full saved record, not only the generated ID.
