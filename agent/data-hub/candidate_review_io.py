from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ReviewItem:
    candidate_id: str
    title: str
    review_action: str
    review_note: str


def stable_candidate_id(extracted_item_id: str, target_date: str, candidate_type: str) -> str:
    digest = hashlib.sha1(f"{extracted_item_id}::{target_date}::{candidate_type}".encode("utf-8")).hexdigest()[:16]
    return f"cand_{digest}"


def slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug[:48]


def suggested_materialized_path(target_date: str, candidate_type: str, candidate_id: str, title: str) -> str:
    if candidate_type == "daily":
        return f"10_Periodic/Daily/{target_date}.md"
    folder = "ADR" if candidate_type == "adr" else "Cards"
    slug = slugify(title)
    suffix = slug if slug else candidate_id[-8:]
    return f"40_Knowledge/{folder}/{target_date}-{suffix}.md"


def render_candidate_markdown(target_date: str, rows: list) -> str:
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row["candidate_type"]].append(row)

    parts = [
        "---",
        "type: candidate-review",
        f"date: {target_date}",
        "status: active",
        "---",
        "",
        f"# Candidate Review {target_date}",
        "",
        "审核动作：`accept` / `reject` / `merge` / `defer`",
        "",
    ]

    for candidate_type in ("daily", "adr", "card"):
        bucket = grouped.get(candidate_type, [])
        parts.append(f"## {candidate_type.upper()}")
        if not bucket:
            parts.append("")
            parts.append("- 无")
            parts.append("")
            continue
        for row in bucket:
            meta = json.loads(row["metadata_json"] or "{}")
            path_hint = row["materialized_path"] or suggested_materialized_path(
                target_date, row["candidate_type"], row["id"], row["title"]
            )
            review_action = {
                "accepted": "accept",
                "rejected": "reject",
                "deferred": "defer",
                "merged": "merge",
            }.get(row["status"], "pending")
            source_path = meta.get("path", "")
            source_label = f"`{meta.get('source_type', 'unknown')}` / `{meta.get('document_title', '')}`"
            if source_path:
                source_label += f" / `{Path(source_path).name}`"
            extracted_item_id = row["extracted_item_id"] if "extracted_item_id" in row.keys() else ""
            parts.extend(
                [
                    "",
                    f"### {row['title']}",
                    f"- candidate_id: `{row['id']}`",
                    f"- status: `{row['status']}`",
                    f"- review_action: `{review_action}`",
                    f"- confidence: `{float(row['confidence']):.2f}`",
                    f"- source: {source_label}",
                    f"- trace: `{extracted_item_id}`" if extracted_item_id else "- trace: (unknown)",
                    f"- suggested_action: `{candidate_type}`",
                    f"- suggested_path: `{path_hint}`",
                    "- review_note: ",
                    "",
                    "```text",
                    str(row["content"]).strip(),
                    "```",
                ]
            )
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def parse_candidate_review(path: Path) -> list[ReviewItem]:
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"^### ", text, flags=re.MULTILINE)
    items: list[ReviewItem] = []

    for section in sections[1:]:
        lines = section.splitlines()
        title = lines[0].strip()
        body = "\n".join(lines[1:])

        candidate_match = re.search(r"^- candidate_id: `([^`]+)`", body, flags=re.MULTILINE)
        action_match = re.search(r"^- review_action: `([^`]+)`", body, flags=re.MULTILINE)
        note_match = re.search(r"^- review_note:\s*(.*)$", body, flags=re.MULTILINE)
        if not candidate_match:
            continue

        items.append(
            ReviewItem(
                candidate_id=candidate_match.group(1).strip(),
                title=title,
                review_action=(action_match.group(1).strip().lower() if action_match else "pending"),
                review_note=(note_match.group(1).strip() if note_match else ""),
            )
        )

    return items
