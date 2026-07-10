from __future__ import annotations

from pathlib import Path

from .common import (
    Chunk,
    Item,
    classify_wiki_item,
    first_non_empty_line,
    normalize_title_from_filename,
    preprocess_wiki_text,
    split_wiki_blocks,
)


def parse(path: Path) -> tuple[str, list[Chunk], list[Item], dict]:
    text = preprocess_wiki_text(path.read_text(encoding="utf-8"))
    first_line = first_non_empty_line(text)
    title = normalize_title_from_filename(path)
    if first_line.startswith("#"):
        title = first_line.lstrip("#").strip() or title

    blocks = split_wiki_blocks(text)
    chunks: list[Chunk] = []
    items: list[Item] = []

    for idx, block in enumerate(blocks):
        first = block.splitlines()[0].strip()
        if first.startswith("#"):
            chunk_type = "heading"
        elif first.startswith("-"):
            chunk_type = "bullet"
        else:
            chunk_type = "paragraph"

        chunks.append(
            Chunk(
                chunk_type=chunk_type,
                locator=f"block:{idx + 1}",
                content=block,
                metadata={"line_count": len(block.splitlines())},
            )
        )
        item_type, confidence = classify_wiki_item(block)
        items.append(
            Item(
                item_type=item_type,
                title=first[:80],
                content=block,
                confidence=confidence,
                chunk_index=idx,
                metadata={"source_format": "markdown", "source_kind": "wiki_page"},
            )
        )

    meta = {
        "file_name": path.name,
        "source_format": "markdown",
        "source_kind": "wiki_page",
        "block_count": len(blocks),
    }
    return title, chunks, items, meta
