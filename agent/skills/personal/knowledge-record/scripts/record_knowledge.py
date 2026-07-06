#!/usr/bin/env python3
"""Record a knowledge artifact into SQLite during an agent conversation.

The agent calls this script directly to push knowledge into the data hub,
bypassing the pipeline's unreliable extraction/review steps.

Usage:
  python record-knowledge.py \\
    --type adr|card|daily \\
    --title "..." \\
    --content "..." \\
    [--background "..."] [--tags "..."] [--impact high|medium|low] \\
    [--references "..."] [--project "..."] [--expires-at "YYYY-MM-DD"] \\
    [--is-actionable] [--why-record "..."] [--agent "codex"] \\
    [--session-id "..."] [--message-id N] [--project-path "..."] \\
    [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path


def find_db_path() -> Path:
    cwd = Path.cwd()
    if (cwd / "data_hub_config.py").exists():
        for candidate in ("db_path", ".db_path"):
            full = cwd / candidate
        for candidate in cwd.rglob("*.runtime.jsonc"):
            try:
                data = json.loads(candidate.read_text())
                path = data.get("paths", {}).get("db_path", "")
                if path:
                    return Path(path).expanduser()
            except (json.JSONDecodeError, KeyError):
                continue
    candidate = Path("template/agent/data-hub/data_hub.db")
    if candidate.exists():
        return candidate.resolve()
    return Path.cwd() / "data_hub.db"


def make_id(title: str, content: str, agent_type: str, timestamp: str) -> str:
    raw = f"{title}|{content}|{agent_type}|{timestamp}"
    return "kr-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def parse_tags(raw: str | None) -> str | None:
    if not raw:
        return None
    tags = [t.strip() for t in raw.split(",") if t.strip()]
    return ",".join(tags) if tags else None


def build_record(args: argparse.Namespace) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    record_date = args.date or date.today().isoformat()
    agent_type = args.agent or os.environ.get("OPENCODE_AGENT", os.environ.get("CODEX_AGENT", ""))
    project_path = args.project_path or os.getcwd()
    session_id = args.session_id or os.environ.get("SESSION_ID", "")
    project = args.project or Path(project_path).name
    record_id = make_id(args.title, args.content, agent_type, now)

    return {
        "id": record_id,
        "record_type": args.type,
        "title": args.title,
        "content": args.content,
        "background": args.background,
        "tags": parse_tags(args.tags),
        "impact": args.impact,
        "is_actionable": 1 if args.is_actionable else 0,
        "references_json": args.references,
        "project": project,
        "expires_at": args.expires_at,
        "why_record": args.why_record,
        "agent_type": agent_type,
        "session_id": session_id,
        "message_id": args.message_id,
        "project_path": project_path,
        "recorded_at": now,
        "candidate_date": record_date,
        "created_at": now,
        "updated_at": now,
        "status": "accepted",
    }


def insert_record(conn: sqlite3.Connection, record: dict) -> str | None:
    conn.execute(
        """
        INSERT OR IGNORE INTO knowledge_records
            (id, record_type, title, content, background, tags, impact,
             is_actionable, references_json, project, expires_at, why_record,
             agent_type, session_id, message_id, project_path,
             recorded_at, candidate_date, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["id"],
            record["record_type"],
            record["title"],
            record["content"],
            record["background"],
            record["tags"],
            record["impact"],
            record["is_actionable"],
            record["references_json"],
            record["project"],
            record["expires_at"],
            record["why_record"],
            record["agent_type"],
            record["session_id"],
            record["message_id"],
            record["project_path"],
            record["recorded_at"],
            record["candidate_date"],
            record["status"],
            record["created_at"],
            record["updated_at"],
        ),
    )
    conn.commit()
    return record["id"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Record knowledge into data hub")
    parser.add_argument("--type", required=True, choices=["adr", "card", "daily"])
    parser.add_argument("--title", required=True)
    parser.add_argument("--content", required=True)
    parser.add_argument("--background", default=None)
    parser.add_argument("--tags", default=None)
    parser.add_argument("--impact", default=None, choices=["high", "medium", "low"])
    parser.add_argument("--is-actionable", action="store_true")
    parser.add_argument("--references", default=None)
    parser.add_argument("--project", default=None)
    parser.add_argument("--expires-at", default=None)
    parser.add_argument("--why-record", default=None)
    parser.add_argument("--agent", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--message-id", type=int, default=None)
    parser.add_argument("--project-path", default=None)
    parser.add_argument("--date", default=None)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-vault-init", action="store_true",
                        help="Skip automatic vault_directory.json creation")
    args = parser.parse_args()

    record = build_record(args)

    if args.dry_run:
        print(f"[dry-run] Would insert to knowledge_records:")
        print(f"  id:         {record['id']}")
        print(f"  type:       {record['record_type']}")
        print(f"  title:      {record['title']}")
        content_preview = record["content"][:80]
        if len(record["content"]) > 80:
            content_preview += "..."
        print(f"  content:    {content_preview}")
        print(f"  tags:       {record['tags']}")
        print(f"  agent:      {record['agent_type']}")
        print(f"  date:       {record['candidate_date']}")
        return 0

    db_path = Path(args.db_path) if args.db_path else find_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        record_id = insert_record(conn, record)
        print(f"Recorded: {record_id} ({record['record_type']}: {record['title']})")

        row = conn.execute(
            "SELECT id, record_type, title, created_at FROM knowledge_records WHERE id = ?",
            (record_id,),
        ).fetchone()
        if row:
            print(f"  id:         {row['id']}")
            print(f"  type:       {row['record_type']}")
            print(f"  title:      {row['title']}")
            print(f"  created:    {row['created_at']}")
            print(f"  status:     accepted (ready for nightly materialization)")
        else:
            print(f"  (already exists — idempotent insert skipped)")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
