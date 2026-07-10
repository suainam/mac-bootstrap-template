from __future__ import annotations

from pathlib import Path

from .common import Chunk, Item, WikiHTMLParser, classify_wiki_item, normalize_title_from_filename


def parse(path: Path) -> tuple[str, list[Chunk], list[Item], dict]:
    parser = WikiHTMLParser()
    parser.feed(path.read_text(encoding="utf-8"))
    blocks = parser.blocks
    title = parser.document_title or normalize_title_from_filename(path)

    chunks: list[Chunk] = []
    items: list[Item] = []
    current_section = ""
    for idx, block in enumerate(blocks):
        content = block["content"]
        chunk_type = block["chunk_type"]
        if idx == 0 and chunk_type == "heading":
            title = content.lstrip("#").strip("- ").strip() or title

        chunks.append(
            Chunk(
                chunk_type=chunk_type,
                locator=f"block:{idx + 1}",
                content=content,
                metadata={"source_format": "html", "section": current_section},
            )
        )
        item_type, confidence = classify_wiki_item(content)
        if chunk_type == "heading":
            content = f"# {content}"
            chunks[-1].content = content
            item_type, confidence = classify_wiki_item(content)
            current_section = content.lstrip("#").strip()
            chunks[-1].metadata["section"] = current_section
        elif chunk_type == "bullet":
            section_lower = current_section.lower()
            if any(token in section_lower for token in ("决策", "decision")):
                item_type, confidence = "decision", max(confidence, 0.78)
            elif any(token in section_lower for token in ("行动项", "action", "待办")):
                item_type, confidence = "action", max(confidence, 0.82)
        if idx == 0 and chunk_type == "heading":
            item_type = "summary"
            confidence = max(confidence, 0.8)
        items.append(
            Item(
                item_type=item_type,
                title=content[:80],
                content=content,
                confidence=confidence,
                chunk_index=idx,
                metadata={"source_format": "html", "source_kind": "wiki_html", "section": current_section},
            )
        )

    meta = {
        "file_name": path.name,
        "source_format": "html",
        "source_kind": "wiki_html",
        "block_count": len(blocks),
    }
    return title, chunks, items, meta
