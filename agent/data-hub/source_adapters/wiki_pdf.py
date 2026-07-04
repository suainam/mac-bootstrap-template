from __future__ import annotations

from pathlib import Path

from .common import (
    Chunk,
    Item,
    classify_wiki_item,
    first_non_empty_line,
    normalize_title_from_filename,
    preprocess_pdf_text,
)


def parse(path: Path) -> tuple[str, list[Chunk], list[Item], dict]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "pypdf is required for wiki_pdf ingestion; install it into template/.venv first"
        ) from exc

    reader = PdfReader(str(path))
    chunks: list[Chunk] = []
    items: list[Item] = []
    title = normalize_title_from_filename(path)
    nonempty_pages = 0

    for page_idx, page in enumerate(reader.pages):
        text = preprocess_pdf_text(page.extract_text() or "")
        if not text:
            continue
        nonempty_pages += 1
        if page_idx == 0:
            first_line = first_non_empty_line(text)
            if first_line:
                title = first_line[:120]

        chunk_index = len(chunks)
        chunks.append(
            Chunk(
                chunk_type="page",
                locator=f"page:{page_idx + 1}",
                content=text,
                metadata={"page": page_idx + 1, "source_format": "pdf"},
            )
        )
        item_type, confidence = classify_wiki_item(text)
        items.append(
            Item(
                item_type="summary" if page_idx == 0 else item_type,
                title=(first_non_empty_line(text) or f"page {page_idx + 1}")[:80],
                content=text,
                confidence=0.8 if page_idx == 0 else confidence,
                chunk_index=chunk_index,
                metadata={"source_format": "pdf", "page": page_idx + 1, "source_kind": "wiki_pdf"},
            )
        )

    meta = {
        "file_name": path.name,
        "source_format": "pdf",
        "source_kind": "wiki_pdf",
        "page_count": len(reader.pages),
        "nonempty_pages": nonempty_pages,
    }
    return title, chunks, items, meta
