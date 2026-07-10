from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from data_hub_config import SourceInput, get_runtime_config

from .common import Chunk, Item, sha256_bytes, sha256_text
from .meeting_markdown import parse as parse_meeting_markdown
from .wiki_markdown import parse as parse_wiki_markdown
from .wiki_pdf import parse as parse_wiki_pdf
from .wiki_html import parse as parse_wiki_html
from .xmind_adapter import parse as parse_xmind


ParserFn = Callable[[Path], tuple[str, list[Chunk], list[Item], dict]]
HashFn = Callable[[Path], str]


def hash_text_file(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8"))


def hash_binary_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


SOURCE_DIR_NAMES = {
    "meeting_note": ("raw/sources/Meetings", "*.md"),
    "mind_map": ("raw/sources/Mindmaps", "*.xmind"),
    "wiki_page": ("raw/sources/Wiki-Clips", "*.md"),
    "wiki_pdf": ("raw/sources/Wiki-Clips", "*.pdf"),
    "wiki_html": ("raw/sources/Wiki-Clips", "*.html"),
}


SOURCE_HANDLERS: dict[str, tuple[ParserFn, HashFn]] = {
    "meeting_note": (parse_meeting_markdown, hash_text_file),
    "mind_map": (parse_xmind, hash_binary_file),
    "wiki_page": (parse_wiki_markdown, hash_text_file),
    "wiki_pdf": (parse_wiki_pdf, hash_binary_file),
    "wiki_html": (parse_wiki_html, hash_text_file),
}


class SourceAdapterRegistry:
    def __init__(
        self,
        handlers: dict[str, tuple[ParserFn, HashFn]] | None = None,
        inputs: list[SourceInput] | None = None,
    ):
        self.handlers = handlers or SOURCE_HANDLERS
        self.inputs = inputs or get_runtime_config().sources

    def iter_source_files(self, vault_dir: Path) -> Iterable[tuple[str, Path]]:
        for source in self.inputs:
            root = vault_dir / source.relative_root
            if not root.exists():
                continue
            yield from ((source.source_type, path) for path in sorted(root.glob(source.pattern)))

    def parse_source(self, source_type: str, path: Path) -> tuple[str, list[Chunk], list[Item], dict, str]:
        parser, hash_fn = self.handlers[source_type]
        title, chunks, items, metadata = parser(path)
        return title, chunks, items, metadata, hash_fn(path)


def iter_source_files(vault_dir: Path) -> Iterable[tuple[str, Path]]:
    yield from SourceAdapterRegistry().iter_source_files(vault_dir)


def parse_source(source_type: str, path: Path) -> tuple[str, list[Chunk], list[Item], dict, str]:
    return SourceAdapterRegistry().parse_source(source_type, path)
