from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import zipfile


@dataclass
class Chunk:
    chunk_type: str
    locator: str
    content: str
    metadata: dict


@dataclass
class Item:
    item_type: str
    title: str
    content: str
    confidence: float
    chunk_index: int | None
    metadata: dict


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def normalize_title_from_filename(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", stem)
    return stem.replace("_", " ").strip() or path.stem


def preprocess_meeting_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"(?<!\n)(摘要)\s*", r"\n\1\n", text)
    text = re.sub(r"(?<!\n)(待办)\s*", r"\n\1\n", text)
    text = re.sub(r"(?<!\n)(\d+\.\s+)", r"\n\1", text)
    text = re.sub(r"(?<!\n)(·\s*)", r"\n· ", text)
    return text.strip()


def preprocess_wiki_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"(?<!\n)(#+\s+)", r"\n\1", text)
    text = re.sub(r"(?<!\n)(\-\s+)", r"\n\1", text)
    return text.strip()


def preprocess_pdf_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_html_text(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_meeting_blocks(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines()]
    blocks: list[str] = []
    current: list[str] = []
    bullet_re = re.compile(r"^[\-\*\u00b7\u25cf\u25cb\u25a0]|^TODO\b", re.IGNORECASE)
    section_re = re.compile(r"^\d+\.\s+")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue

        starts_new_block = bool(bullet_re.match(stripped))
        starts_new_section = bool(section_re.match(stripped)) or stripped in {"摘要", "待办"}
        if starts_new_block and current:
            blocks.append("\n".join(current).strip())
            current = []
        elif starts_new_section and current:
            blocks.append("\n".join(current).strip())
            current = []
        current.append(line)

    if current:
        blocks.append("\n".join(current).strip())
    return blocks


def split_wiki_blocks(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines()]
    blocks: list[str] = []
    current: list[str] = []
    header_re = re.compile(r"^#{1,6}\s+")
    bullet_re = re.compile(r"^-\s+")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue

        if (header_re.match(stripped) or bullet_re.match(stripped)) and current:
            blocks.append("\n".join(current).strip())
            current = []
        current.append(line)

    if current:
        blocks.append("\n".join(current).strip())
    return blocks


def classify_meeting_item(content: str) -> tuple[str, float]:
    lowered = content.lower()
    first_line = content.splitlines()[0].strip()
    if first_line == "待办" or "todo" in lowered:
        return "action", 0.88
    if re.match(r"^\d+\.\s+", first_line):
        return "topic", 0.78
    if first_line.startswith("·") or first_line.startswith("-"):
        if any(token in content for token in ("拉取", "发送", "组织", "评估", "@")):
            return "action", 0.84
        return "fact", 0.68
    if "达成初步共识" in content or "决定" in content or "改为" in content or "取消" in content:
        return "decision", 0.83
    if "风险" in content or "影响" in content:
        return "risk", 0.74
    if "需" in content or "需要" in content:
        return "action", 0.8
    if "期望" in content or re.search(r"\b\d{1,2}\.\d{1,2}\b", content):
        return "open_loop", 0.72
    if "讨论" in content or "思路" in content or "设计" in content:
        return "topic", 0.65
    return "fact", 0.6


def classify_wiki_item(content: str) -> tuple[str, float]:
    first_line = content.splitlines()[0].strip()
    lowered = content.lower()
    if first_line.startswith("#"):
        return "topic", 0.82
    if first_line.startswith("-"):
        if any(token in content for token in ("TODO", "待办", "follow-up", "next step")):
            return "action", 0.82
        if any(token in lowered for token in ("决定", "约定", "规则", "decision")):
            return "decision", 0.78
        if any(token in lowered for token in ("行动项", "action", "owner", "负责")):
            return "action", 0.8
        return "fact", 0.68
    if any(token in lowered for token in ("decision", "决定", "约定", "规则")):
        return "decision", 0.78
    if any(token in lowered for token in ("risk", "风险", "限制", "caveat")):
        return "risk", 0.74
    return "fact", 0.62


class WikiHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self.capture_stack: list[dict] = []
        self.ignore_depth = 0
        self.document_title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self.ignore_depth += 1
            return
        if self.ignore_depth:
            return
        if tag in {"title", "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "td", "th"}:
            self.capture_stack.append({"tag": tag, "parts": [], "cells": []})
            return
        if tag == "br" and self.capture_stack:
            self.capture_stack[-1]["parts"].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.ignore_depth = max(0, self.ignore_depth - 1)
            return
        if self.ignore_depth or not self.capture_stack:
            return

        frame = self.capture_stack[-1]
        if frame["tag"] != tag:
            return

        frame = self.capture_stack.pop()
        text = normalize_html_text("".join(frame["parts"]))
        if tag == "title":
            if text:
                self.document_title = text[:120]
            return
        if tag in {"td", "th"}:
            if self.capture_stack and self.capture_stack[-1]["tag"] == "tr" and text:
                self.capture_stack[-1]["cells"].append(text)
            return
        if tag == "tr":
            if frame["cells"]:
                self.blocks.append({"chunk_type": "table_row", "content": " | ".join(frame["cells"])})
            return
        if not text:
            return
        chunk_type = "heading" if tag.startswith("h") else "bullet" if tag == "li" else "paragraph"
        if chunk_type == "bullet":
            text = f"- {text}"
        self.blocks.append({"chunk_type": chunk_type, "content": text})

    def handle_data(self, data: str) -> None:
        if self.ignore_depth or not self.capture_stack:
            return
        self.capture_stack[-1]["parts"].append(data)


def load_xmind_content(path: Path) -> tuple[dict, dict]:
    with zipfile.ZipFile(path) as zf:
        content = json.loads(zf.read("content.json").decode("utf-8"))
    sheet = content[0]
    return sheet, sheet["rootTopic"]
