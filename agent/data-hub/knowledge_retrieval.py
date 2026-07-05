#!/usr/bin/env python3
"""
Build a reusable context packet from existing Daily / ADR / Card notes and open
knowledge candidates before a knowledge-heavy task starts.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from data_hub_config import get_runtime_config


def load_env() -> None:
    return None


load_env()

RUNTIME_CONFIG = get_runtime_config()
OBSIDIAN_VAULT_DIR = RUNTIME_CONFIG.paths.vault_dir
DB_PATH = RUNTIME_CONFIG.paths.db_path


@dataclass
class RetrievalHit:
    path: str
    title: str
    score: int
    snippet: str
    date: str | None = None


def tokenize(value: str) -> list[str]:
    lowered = value.lower()
    token = []
    tokens: list[str] = []
    for ch in lowered:
        if ch.isalnum():
            token.append(ch)
            continue
        if token:
            tokens.append("".join(token))
            token = []
    if token:
        tokens.append("".join(token))
    return [tok for tok in tokens if len(tok) >= 2]


def dedupe_keywords(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        for token in tokenize(value):
            if token not in seen:
                seen.add(token)
                ordered.append(token)
    return ordered


def score_text(text: str, keywords: list[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(keyword) for keyword in keywords)


def extract_snippet(text: str, keywords: list[str], limit: int = 220) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    for line in lines:
        lowered = line.lower()
        if any(keyword in lowered for keyword in keywords):
            return line[:limit]
    return lines[0][:limit]


def date_in_range(value: str | None, date_from: str | None, date_to: str | None) -> bool:
    if not value:
        return True
    if date_from and value < date_from:
        return False
    if date_to and value > date_to:
        return False
    return True


def scan_markdown_bucket(
    relative_dir: str,
    keywords: list[str],
    date_from: str | None,
    date_to: str | None,
    project: str | None,
    limit: int,
) -> list[dict]:
    root = OBSIDIAN_VAULT_DIR / relative_dir
    if not root.exists():
        return []

    hits: list[RetrievalHit] = []
    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        score = score_text(text + "\n" + str(path), keywords)
        if score <= 0:
            continue

        stem_date = path.stem[:10] if len(path.stem) >= 10 else None
        if not date_in_range(stem_date, date_from, date_to):
            continue
        if project and project.lower() not in text.lower() and project.lower() not in str(path).lower():
            continue

        title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
        hits.append(
            RetrievalHit(
                path=str(path.relative_to(OBSIDIAN_VAULT_DIR)),
                title=title,
                score=score,
                snippet=extract_snippet(text, keywords),
                date=stem_date,
            )
        )

    hits.sort(key=lambda item: (-item.score, item.path))
    return [asdict(hit) for hit in hits[:limit]]


def fetch_open_loops(
    keywords: list[str],
    project: str | None,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> list[dict]:
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT candidate_date, id, candidate_type, status, title, content, confidence, metadata_json
            FROM knowledge_candidates
            WHERE status IN ('pending', 'deferred')
            ORDER BY candidate_date DESC, confidence DESC, rowid ASC
            """
        ).fetchall()
    finally:
        conn.close()

    results = []
    for row in rows:
        if not date_in_range(row["candidate_date"], date_from, date_to):
            continue

        text = f"{row['title']}\n{row['content']}\n{row['metadata_json'] or ''}"
        score = score_text(text, keywords)
        if score <= 0:
            continue
        if project and project.lower() not in text.lower():
            continue

        results.append(
            {
                "candidate_id": row["id"],
                "candidate_date": row["candidate_date"],
                "candidate_type": row["candidate_type"],
                "status": row["status"],
                "title": row["title"],
                "score": score,
                "confidence": float(row["confidence"]),
            }
        )

    results.sort(key=lambda item: (-item["score"], item["candidate_date"], item["candidate_id"]))
    return results[:limit]


def build_reuse_recommendations(
    matched_daily: list[dict],
    matched_adrs: list[dict],
    matched_cards: list[dict],
    open_loops: list[dict],
) -> list[str]:
    recommendations: list[str] = []
    if matched_adrs:
        recommendations.append("Read the matched ADRs first and preserve their chosen constraints in follow-up work.")
    if matched_cards:
        recommendations.append("Reuse the highest-scoring Cards as defaults before drafting new conclusions.")
    if matched_daily:
        recommendations.append("Scan recent Daily notes for unresolved context before asking the model to summarize again.")
    if open_loops:
        recommendations.append("Resolve or acknowledge the top open loops before promoting new knowledge for the same topic.")
    if not recommendations:
        recommendations.append("No reusable context found. Continue, but record fresh claims so they can be promoted later.")
    return recommendations


def build_retrieval_packet(
    task_goal: str,
    keywords: list[str],
    project: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    keyword_tokens = dedupe_keywords([task_goal, *keywords, project or ""])
    matched_daily = scan_markdown_bucket("10_Periodic/Daily", keyword_tokens, date_from, date_to, project, limit=5)
    matched_adrs = scan_markdown_bucket("40_Knowledge/ADR", keyword_tokens, date_from, date_to, project, limit=5)
    matched_cards = scan_markdown_bucket("40_Knowledge/Cards", keyword_tokens, date_from, date_to, project, limit=5)
    open_loops = fetch_open_loops(keyword_tokens, project, date_from, date_to, limit=8)

    return {
        "task_goal": task_goal,
        "keywords": keyword_tokens,
        "project": project,
        "date_range": {"from": date_from, "to": date_to},
        "matched_daily": matched_daily,
        "matched_adrs": matched_adrs,
        "matched_cards": matched_cards,
        "open_loops": open_loops,
        "reuse_recommendations": build_reuse_recommendations(
            matched_daily,
            matched_adrs,
            matched_cards,
            open_loops,
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a structured retrieval packet for knowledge reuse.")
    parser.add_argument("--task-goal", required=True)
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--project")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    packet = build_retrieval_packet(
        task_goal=args.task_goal,
        keywords=args.keyword,
        project=args.project,
        date_from=args.date_from,
        date_to=args.date_to,
    )
    rendered = json.dumps(packet, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
