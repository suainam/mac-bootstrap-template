#!/usr/bin/env python3
"""
Apply lightweight review actions from a candidate markdown file into SQLite and
materialize accepted items into the Obsidian vault.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from candidate_review_io import ReviewItem, parse_candidate_review
from data_hub_config import get_runtime_config
from db_helper import get_db_connection
from execution_logger import ExecutionLogger


def load_env() -> None:
    return None


load_env()

RUNTIME_CONFIG = get_runtime_config()
OBSIDIAN_VAULT_DIR = RUNTIME_CONFIG.paths.vault_dir
DB_PATH = RUNTIME_CONFIG.paths.db_path
CANDIDATE_DIR = OBSIDIAN_VAULT_DIR / "60_Inbox" / "Candidates"


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
    conn = get_db_connection()
    logger = ExecutionLogger(conn, target_date)
    log_id = logger.start("materialize_candidates")

    try:
        # First, apply human review from markdown if exists
        review_path = CANDIDATE_DIR / f"{target_date}.md"
        changed = 0
        if review_path.exists():
            review_items = parse_candidate_review(review_path)
            changed, _ = apply_review_actions(conn, target_date, review_items)

        # Then materialize all accepted candidates (auto or manual)
        cursor = conn.execute(
            "SELECT * FROM knowledge_candidates WHERE candidate_date = ? AND status = 'accepted'",
            (target_date,)
        )
        accepted_candidates = cursor.fetchall()
        materialized = 0

        for row in accepted_candidates:
            if row["materialized_path"]:
                continue  # Already materialized

            metadata = json.loads(row["metadata_json"] or "{}")
            source = f"{metadata.get('source_type', 'unknown')} / {metadata.get('document_title', '')}"

            # Materialize based on candidate_type
            if row["candidate_type"] == "daily":
                materialized_path = f"10_Periodic/Daily/{target_date}.md"
                target_path = OBSIDIAN_VAULT_DIR / materialized_path
                materialize_daily_candidate(target_path, row["id"], row["title"], row["content"])
            elif row["candidate_type"] in {"card", "adr"}:
                folder = "ADR" if row["candidate_type"] == "adr" else "Cards"
                materialized_path = f"40_Knowledge/{folder}/{target_date}-{row['id'][-8:]}.md"
                target_path = OBSIDIAN_VAULT_DIR / materialized_path
                materialize_note_candidate(
                    target_path,
                    row["candidate_type"],
                    target_date,
                    row["title"],
                    row["content"],
                    source,
                    row["id"],
                )
            else:
                continue

            # Update materialized_path
            conn.execute(
                "UPDATE knowledge_candidates SET materialized_path = ? WHERE id = ?",
                (materialized_path, row["id"])
            )
            materialized += 1

        # Also materialize skill-generated records
        cursor = conn.execute(
            "SELECT * FROM knowledge_records WHERE candidate_date = ? AND status = 'accepted'",
            (target_date,)
        )
        skill_rows = cursor.fetchall()

        for row in skill_rows:
            if row["materialized_path"]:
                continue

            source = f"skill-record: {row['agent_type']}"

            if row["record_type"] == "daily":
                materialized_path = f"10_Periodic/Daily/{target_date}.md"
                target_path = OBSIDIAN_VAULT_DIR / materialized_path
                materialize_daily_candidate(target_path, row["id"], row["title"], row["content"])
            elif row["record_type"] in {"card", "adr"}:
                folder = "ADR" if row["record_type"] == "adr" else "Cards"
                materialized_path = f"40_Knowledge/{folder}/{target_date}-{row['id'][-8:]}.md"
                target_path = OBSIDIAN_VAULT_DIR / materialized_path
                materialize_note_candidate(
                    target_path,
                    row["record_type"],
                    target_date,
                    row["title"],
                    row["content"],
                    source,
                    row["id"],
                )
            else:
                continue

            conn.execute(
                "UPDATE knowledge_records SET materialized_path = ? WHERE id = ?",
                (materialized_path, row["id"])
            )
            materialized += 1

        conn.commit()
        logger.complete(log_id, records_affected=materialized, metadata={"changed": changed, "materialized": materialized, "from_skill": len(skill_rows)})
        print(f"[materialize_candidates] {target_date}: {changed} reviewed, {materialized} materialized (skill: {len(skill_rows)})")

    except Exception as e:
        logger.fail(log_id, str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
