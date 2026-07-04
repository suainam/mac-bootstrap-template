from __future__ import annotations

from pathlib import Path

from .common import (
    Chunk,
    Item,
    classify_meeting_item,
    first_non_empty_line,
    normalize_title_from_filename,
    preprocess_meeting_text,
    split_meeting_blocks,
)


def parse(path: Path) -> tuple[str, list[Chunk], list[Item], dict]:
    text = preprocess_meeting_text(path.read_text(encoding="utf-8"))
    first_line = first_non_empty_line(text)
    title = normalize_title_from_filename(path) if first_line.strip() in {"摘要", "会议纪要", "纪要"} else (first_line or normalize_title_from_filename(path))
    blocks = split_meeting_blocks(text)
    chunks: list[Chunk] = []
    items: list[Item] = []

    for idx, block in enumerate(blocks):
        chunk_type = "bullet" if any(block.startswith(marker) for marker in ("●", "○", "■", "- ")) else "paragraph"
        chunks.append(
            Chunk(
                chunk_type=chunk_type,
                locator=f"block:{idx + 1}",
                content=block,
                metadata={"line_count": len(block.splitlines())},
            )
        )
        item_type, confidence = classify_meeting_item(block)
        item_title = block.splitlines()[0][:80]
        items.append(
            Item(
                item_type=item_type,
                title=item_title,
                content=block,
                confidence=confidence,
                chunk_index=idx,
                metadata={"source_format": "markdown"},
            )
        )

        if block.splitlines()[0].strip() == "待办":
            for subline in block.splitlines()[1:]:
                stripped = subline.strip()
                if not stripped.startswith("·"):
                    continue
                items.append(
                    Item(
                        item_type="action",
                        title=stripped[:80],
                        content=stripped,
                        confidence=0.9,
                        chunk_index=idx,
                        metadata={"source_format": "markdown", "derived_from": "todo_block"},
                    )
                )

    meta = {
        "file_name": path.name,
        "source_format": "markdown",
        "block_count": len(blocks),
    }
    return title, chunks, items, meta
