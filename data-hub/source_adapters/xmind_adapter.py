from __future__ import annotations

from pathlib import Path

from .common import Chunk, Item, load_xmind_content


def flatten_topic(topic: dict, parent_path: list[str], depth: int, chunks: list[Chunk], items: list[Item]) -> None:
    title = (topic.get("title") or "").strip()
    path_parts = parent_path + ([title] if title else [])
    locator = " > ".join(path_parts) if path_parts else "root"

    if title:
        chunk_index = len(chunks)
        chunks.append(
            Chunk(
                chunk_type="topic",
                locator=locator,
                content=title,
                metadata={
                    "depth": depth,
                    "has_href": bool(topic.get("href")),
                    "has_image": bool(topic.get("image")),
                },
            )
        )
        item_type = "topic" if depth <= 1 else "fact"
        confidence = 0.7 if depth <= 1 else 0.58
        items.append(
            Item(
                item_type=item_type,
                title=title[:80],
                content=locator,
                confidence=confidence,
                chunk_index=chunk_index,
                metadata={"depth": depth},
            )
        )

    children = topic.get("children", {})
    for key in ("attached", "summary", "detached"):
        for child in children.get(key, []):
            flatten_topic(child, path_parts, depth + 1, chunks, items)


def parse(path: Path) -> tuple[str, list[Chunk], list[Item], dict]:
    sheet, root = load_xmind_content(path)
    title = root.get("title") or path.stem
    chunks: list[Chunk] = []
    items: list[Item] = []
    flatten_topic(root, [], 0, chunks, items)

    meta = {
        "file_name": path.name,
        "sheet_title": sheet.get("title"),
        "source_format": "xmind",
        "topic_count": len(chunks),
    }
    return title, chunks, items, meta
