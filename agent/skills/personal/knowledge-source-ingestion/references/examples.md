# Examples

Use this skill for requests like:

- "把这份会议纪要接进 data-hub，看能不能抽出待办和决策"
- "这个 xmind 能不能入库，并在日报里体现候选项"
- "新来的 wiki 导出格式变了，修一下 parser"
- "抽取质量不对，哪些 action 被识别成了 fact"
- "给外部材料新增一种 source adapter"
- "把 Confluence 导出的 PDF wiki 接进 SQLite"
- "把 SQLite -> 候选审核 -> Obsidian 日报/知识卡片这条链跑通"

Expected process shape:

1. inspect the real sample file
2. choose or extend the adapter
3. re-run `ingest_sources.py`
4. inspect `source_documents`, `document_chunks`, `extracted_items`
5. decide whether the problem is boundary drift, classification drift, or missing fallback
6. when explicitly asked, generate `knowledge_candidates` and materialize only reviewed `accept` items
