#!/usr/bin/env python3
"""
Apply lightweight review actions from a candidate markdown file into SQLite and
materialize accepted items into the Obsidian vault.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from candidate_review_io import ReviewItem, parse_candidate_review


def load_env() -> None:
    env_path = Path.home() / "work/config/mac-bootstrap/private/agent/.obsidian_daily.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")


load_env()

OBSIDIAN_VAULT_DIR = Path(os.path.expandvars(os.environ.get("OBSIDIAN_VAULT_DIR", str(Path.home() / "work/knowledge"))))
DB_PATH = Path(os.path.expandvars(os.environ.get("AGENT_DB_PATH", str(Path.home() / "work/config/mac-bootstrap/private/agent/data/agent_history.db"))))
CANDIDATE_DIR = OBSIDIAN_VAULT_DIR / "60_Inbox" / "Candidates"

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema_path = Path(__file__).parent / "schema.sql"
    conn.executescript(schema_path.read_text())
    return conn


def materialize_daily_candidate(target_path: Path, candidate_id: str, title: str, content: str) -> None:
    marker = f"<!-- knowledge_candidate:{candidate_id} -->"
    line = f"- [ ] {title} {marker}"
    if content.strip() and content.strip() != title.strip():
        line = f"- [ ] {title}: {content.strip().replace(chr(10), ' ')} {marker}"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not target_path.exists():
        target_path.write_text(
            "\n".join(
                [
                    "---",
                    "type: journal",
                    "status: active",
                    f"date: {target_path.stem}",
                    "---",
                    "",
                    f"# {target_path.stem}",
                    "",
                    "## 候选事项",
                    "",
                    line,
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return

    text = target_path.read_text(encoding="utf-8")
    if marker in text:
        return

    if "## 候选事项" in text:
        text = re.sub(r"(## 候选事项\s*\n)", r"\1\n" + line + "\n", text, count=1)
    elif "\n## AI 总结" in text:
        text = text.replace("\n## AI 总结", "\n## 候选事项\n\n" + line + "\n\n## AI 总结", 1)
    elif "\n## 明日计划" in text:
        text = text.replace("\n## 明日计划", "\n## 候选事项\n\n" + line + "\n\n## 明日计划", 1)
    else:
        text = text.rstrip() + "\n\n## 候选事项\n\n" + line + "\n"

    target_path.write_text(text, encoding="utf-8")


def render_knowledge_note(candidate_type: str, candidate_date: str, title: str, content: str, source: str, candidate_id: str) -> str:
    note_type = "adr" if candidate_type == "adr" else "knowledge-card"
    return "\n".join(
        [
            "---",
            f"type: {note_type}",
            f"candidate_id: {candidate_id}",
            f"date: {candidate_date}",
            f"source: {source}",
            "status: active",
            "---",
            "",
            f"# {title}",
            "",
            "## 内容",
            "",
            content.strip(),
            "",
        ]
    )


def materialize_note_candidate(target_path: Path, candidate_type: str, candidate_date: str, title: str, content: str, source: str, candidate_id: str) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        text = target_path.read_text(encoding="utf-8")
        if f"candidate_id: {candidate_id}" in text:
            return
    target_path.write_text(
        render_knowledge_note(candidate_type, candidate_date, title, content, source, candidate_id),
        encoding="utf-8",
    )


def apply_review_actions(conn: sqlite3.Connection, target_date: str, review_items: list[ReviewItem]) -> tuple[int, int]:
    review_map = {item.candidate_id: item for item in review_items}
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, candidate_type, title, content, candidate_date, metadata_json, materialized_path
        FROM knowledge_candidates
        WHERE candidate_date = ?
        ORDER BY rowid ASC
        """,
        (target_date,),
    )
    rows = cursor.fetchall()
    changed = 0
    materialized = 0
    now = datetime.now().isoformat(timespec="seconds")

    for row in rows:
        review = review_map.get(row["id"])
        if not review:
            continue

        action = review.review_action
        if action == "pending":
            continue
        if action not in {"accept", "reject", "defer", "merge"}:
            continue

        status_map = {
            "accept": "accepted",
            "reject": "rejected",
            "defer": "deferred",
            "merge": "merged",
        }

        materialized_path = row["materialized_path"]
        metadata = json.loads(row["metadata_json"] or "{}")
        source = f"{metadata.get('source_type', 'unknown')} / {metadata.get('document_title', '')}"

        if action == "accept":
            if row["candidate_type"] == "daily":
                materialized_path = f"10_Periodic/Daily/{target_date}.md"
                materialize_daily_candidate(
                    OBSIDIAN_VAULT_DIR / materialized_path,
                    row["id"],
                    row["title"],
                    row["content"],
                )
            else:
                folder = "ADR" if row["candidate_type"] == "adr" else "Cards"
                materialized_path = materialized_path or f"40_Knowledge/{folder}/{target_date}-{row['id'][-8:]}.md"
                materialize_note_candidate(
                    OBSIDIAN_VAULT_DIR / materialized_path,
                    row["candidate_type"],
                    target_date,
                    row["title"],
                    row["content"],
                    source,
                    row["id"],
                )
            materialized += 1

        conn.execute(
            """
            UPDATE knowledge_candidates
            SET status = ?, review_note = ?, materialized_path = ?, updated_at = ?
            WHERE id = ?
            """,
            (status_map[action], review.review_note, materialized_path, now, row["id"]),
        )
        changed += 1

    conn.commit()
    return changed, materialized


def main() -> None:
    target_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    review_path = CANDIDATE_DIR / f"{target_date}.md"
    if not review_path.exists():
        raise SystemExit(f"candidate review file not found: {review_path}")

    review_items = parse_candidate_review(review_path)
    conn = get_db_connection()
    try:
        changed, materialized = apply_review_actions(conn, target_date, review_items)
    finally:
        conn.close()

    generator = Path(__file__).parent / "generate_candidates.py"
    subprocess.run([sys.executable, str(generator), target_date], check=True)

    print(
        f"[materialize_candidates] {target_date}: {changed} reviewed, "
        f"{materialized} materialized from {review_path}"
    )


if __name__ == "__main__":
    main()
