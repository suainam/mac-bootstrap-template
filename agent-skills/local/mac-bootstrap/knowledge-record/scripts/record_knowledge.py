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
import importlib.util
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

ALLOWED_AGENT_TYPES = {"codex", "claude", "agy", "opencode"}
TAG_PATTERN = re.compile(r"^[\u4e00-\u9fff][\u4e00-\u9fff\-]*[\u4e00-\u9fff]$|^[\u4e00-\u9fff]$")
CJK_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")
LATIN_CHAR_PATTERN = re.compile(r"[A-Za-z]")
TEMPLATE_ROOT = Path(__file__).resolve().parents[5]
DATA_HUB_DIR = TEMPLATE_ROOT / "data-hub"


def _load_suggest_module():
    suggest_path = Path(__file__).with_name("suggest_record.py")
    scripts_dir = str(suggest_path.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("knowledge_record_suggest", suggest_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def find_db_path() -> Path:
    cwd = Path.cwd()
    for candidate in (
        cwd / "private" / "agent" / "data_hub.runtime.jsonc",
        cwd / "data_hub.runtime.jsonc",
    ):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text())
            path = data.get("paths", {}).get("db_path", "")
            if path:
                return Path(os.path.expandvars(path)).expanduser()
        except json.JSONDecodeError:
            continue

    if str(DATA_HUB_DIR) not in sys.path:
        sys.path.insert(0, str(DATA_HUB_DIR))
    try:
        from data_hub_config import get_runtime_config

        return get_runtime_config().paths.db_path
    except Exception:
        pass

    candidate = DATA_HUB_DIR / "data_hub.db"
    if candidate.exists():
        return candidate.resolve()
    return cwd / "data_hub.db"


def make_id(title: str, content: str, agent_type: str, project_path: str, record_date: str) -> str:
    raw = f"{title}|{content}|{agent_type}|{project_path}|{record_date}"
    return "kr-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def is_chinese_dominant(text: str) -> bool:
    cjk_count = len(CJK_CHAR_PATTERN.findall(text))
    latin_count = len(LATIN_CHAR_PATTERN.findall(text))
    return cjk_count > 0 and cjk_count >= latin_count


def validate_chinese_dominant(value: str | None, field_name: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    if not is_chinese_dominant(text):
        raise ValueError(f"{field_name} must be Chinese-dominant")
    return text


def parse_tags(raw: str | None) -> str:
    if not raw or not raw.strip():
        raise ValueError("tags are required")
    tags: list[str] = []
    for part in raw.split(","):
        tag = part.strip()
        if not tag:
            continue
        if tag not in tags:
            tags.append(tag)
    if not tags:
        raise ValueError("tags are required")
    invalid_tags = [tag for tag in tags if not TAG_PATTERN.fullmatch(tag)]
    if invalid_tags:
        raise ValueError(f"tags must be non-empty Chinese labels: {', '.join(invalid_tags)}")
    return ",".join(tags)


def validate_agent_type(agent_type: str) -> str:
    normalized = agent_type.strip()
    if not normalized:
        raise ValueError("agent_type is required")
    if normalized not in ALLOWED_AGENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_AGENT_TYPES))
        raise ValueError(f"agent_type must be one of: {allowed}")
    return normalized


def validate_args(args: argparse.Namespace) -> dict[str, str | None]:
    normalized = {
        "title": validate_chinese_dominant(args.title, "title"),
        "content": validate_chinese_dominant(args.content, "content"),
        "tags": parse_tags(args.tags),
    }
    agent_candidate = args.agent or os.environ.get("OPENCODE_AGENT", os.environ.get("CODEX_AGENT", ""))
    normalized["agent_type"] = validate_agent_type(agent_candidate)

    if args.type == "adr":
        normalized["background"] = validate_chinese_dominant(args.background, "background")
        normalized["why_record"] = validate_chinese_dominant(args.why_record, "why_record")
        references = (args.references or "").strip()
        if not references:
            raise ValueError("references are required for adr")
        normalized["references"] = references
    else:
        normalized["background"] = validate_chinese_dominant(args.background, "background") if args.background else None
        normalized["why_record"] = validate_chinese_dominant(args.why_record, "why_record")
        normalized["references"] = (args.references or "").strip() or None

    return normalized


def build_record(args: argparse.Namespace) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    record_date = args.date or date.today().isoformat()
    normalized = validate_args(args)
    agent_type = normalized["agent_type"]
    project_path = args.project_path or os.getcwd()
    session_id = args.session_id or os.environ.get("SESSION_ID", "")
    project = args.project or Path(project_path).name
    record_id = make_id(normalized["title"], normalized["content"], agent_type, project_path, record_date)

    return {
        "id": record_id,
        "record_type": args.type,
        "title": normalized["title"],
        "content": normalized["content"],
        "background": normalized["background"],
        "tags": normalized["tags"],
        "impact": args.impact,
        "is_actionable": 1 if args.is_actionable else 0,
        "references_json": normalized["references"],
        "project": project,
        "expires_at": args.expires_at,
        "why_record": normalized["why_record"],
        "agent_type": agent_type,
        "session_id": session_id,
        "message_id": args.message_id,
        "project_path": project_path,
        "recorded_at": now,
        "candidate_date": record_date,
        "record_revision": "kr-v1",
        "authority": "trusted_agent",
        "source_kind": "live_agent",
        "source_fingerprint": hashlib.sha256(f"{args.title}|{args.content}|{project_path}".encode()).hexdigest(),
        "raw_refs_json": "[]",
        "created_at": now,
        "updated_at": now,
        "status": "accepted",
    }


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Extend older SQLite files to the current knowledge_records contract."""
    existing = set()
    for row in conn.execute("PRAGMA table_info(knowledge_records)").fetchall():
        existing.add(row["name"] if isinstance(row, sqlite3.Row) else row[1])
    required_columns = {
        "background": "TEXT",
        "tags": "TEXT",
        "impact": "TEXT",
        "is_actionable": "INTEGER NOT NULL DEFAULT 0",
        "references_json": "TEXT",
        "project": "TEXT",
        "expires_at": "TEXT",
        "why_record": "TEXT",
        "session_id": "TEXT",
        "message_id": "INTEGER",
        "project_path": "TEXT",
        "materialized_path": "TEXT",
        "record_revision": "TEXT",
        "authority": "TEXT",
        "source_kind": "TEXT",
        "source_fingerprint": "TEXT",
        "raw_refs_json": "TEXT",
    }
    for name, definition in required_columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE knowledge_records ADD COLUMN {name} {definition}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kr_revision ON knowledge_records(record_revision)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS materializations (
            projection_key TEXT PRIMARY KEY,
            record_id TEXT NOT NULL,
            projection_type TEXT NOT NULL,
            logical_target TEXT NOT NULL,
            block_id TEXT NOT NULL,
            target_path TEXT,
            template_version TEXT NOT NULL,
            input_fingerprint TEXT NOT NULL,
            state_watermark TEXT NOT NULL,
            rendered_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'rendered',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(record_id) REFERENCES knowledge_records(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_materializations_record ON materializations(record_id, projection_type)")
    conn.commit()


def insert_record(conn: sqlite3.Connection, record: dict) -> str | None:
    ensure_schema(conn)
    conn.execute(
        """
        INSERT OR IGNORE INTO knowledge_records
            (id, record_type, title, content, background, tags, impact,
             is_actionable, references_json, project, expires_at, why_record,
             agent_type, session_id, message_id, project_path,
             recorded_at, candidate_date, status, record_revision, authority,
             source_kind, source_fingerprint, raw_refs_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            record["record_revision"],
            record["authority"],
            record["source_kind"],
            record["source_fingerprint"],
            record["raw_refs_json"],
            record["created_at"],
            record["updated_at"],
        ),
    )
    conn.commit()
    return record["id"]


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "suggest":
        return _load_suggest_module().main(argv[1:])

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
    args = parser.parse_args(argv)

    try:
        record = build_record(args)
    except ValueError as exc:
        parser.error(str(exc))

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
