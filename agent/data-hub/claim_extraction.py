#!/usr/bin/env python3
"""
Build typed claim packets from landed source items and optionally recent chat
messages. Output stays schema-first JSON for later review and promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from source_dates import document_matches_target


def load_env() -> None:
    env_path = Path.home() / "work/config/mac-bootstrap/private/agent/.obsidian_daily.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")


load_env()

DB_PATH = Path(
    os.path.expandvars(
        os.environ.get(
            "AGENT_DB_PATH",
            str(Path.home() / "work/config/mac-bootstrap/private/agent/data/agent_history.db"),
        )
    )
)


SOURCE_ITEM_TO_CLAIM_TYPE = {
    "fact": "fact",
    "decision": "decision",
    "action": "action",
    "risk": "risk",
    "open_loop": "open_loop",
    "summary": "insight_candidate",
    "topic": "insight_candidate",
}


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def classify_chat_message(text: str) -> tuple[str, float]:
    lowered = text.lower()
    if any(token in lowered for token in ("决定", "采用", "改成", "change to", "switch to")):
        return "decision", 0.75
    if "?" in text or any(token in lowered for token in ("如何", "why", "怎么", "是否", "need to")):
        return "open_loop", 0.6
    if any(token in lowered for token in ("todo", "待办", "follow up", "next step", "需要处理")):
        return "action", 0.65
    if any(token in lowered for token in ("风险", "blocked", "阻塞", "issue", "问题")):
        return "risk", 0.55
    return "insight_candidate", 0.45


def fetch_source_claims(conn: sqlite3.Connection, target_date: str) -> tuple[list[dict], list[dict]]:
    rows = conn.execute(
        """
        SELECT d.id AS document_id, d.source_type, d.title AS document_title, d.path, d.version_tag, d.captured_at,
               i.id AS extracted_item_id, i.item_type, i.title, i.content, i.confidence, i.metadata_json
        FROM source_documents d
        JOIN extracted_items i ON i.document_id = d.id
        ORDER BY d.captured_at DESC, d.rowid DESC, i.rowid ASC
        """
    ).fetchall()

    claim_packets: list[dict] = []
    evidence_links: list[dict] = []
    for row in rows:
        if not document_matches_target(
            row["path"],
            row["version_tag"],
            row["captured_at"],
            row["metadata_json"],
            target_date,
        ):
            continue
        claim_type = SOURCE_ITEM_TO_CLAIM_TYPE.get(row["item_type"], "insight_candidate")
        claim_id = stable_id("clm", row["extracted_item_id"], target_date, claim_type)
        evidence_id = stable_id("evd", row["extracted_item_id"], row["document_id"])
        claim_packets.append(
            {
                "claim_id": claim_id,
                "claim_type": claim_type,
                "title": row["title"],
                "content": row["content"],
                "confidence": float(row["confidence"]),
                "source_kind": "extracted_item",
                "source_ref": {
                    "document_id": row["document_id"],
                    "document_title": row["document_title"],
                    "source_type": row["source_type"],
                    "path": row["path"],
                    "extracted_item_id": row["extracted_item_id"],
                },
                "source_date": target_date,
            }
        )
        evidence_links.append(
            {
                "claim_id": claim_id,
                "evidence_id": evidence_id,
                "evidence_type": "external_source",
                "source_table": "extracted_items",
                "source_id": row["extracted_item_id"],
            }
        )
    return claim_packets, evidence_links


def fetch_chat_claims(conn: sqlite3.Connection, target_date: str) -> tuple[list[dict], list[dict]]:
    rows = conn.execute(
        """
        SELECT m.id, m.timestamp, m.content, s.agent_type, s.project_path
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE m.role = 'user' AND m.timestamp LIKE ?
        ORDER BY m.timestamp ASC, m.id ASC
        """,
        (f"{target_date}%",),
    ).fetchall()

    claim_packets: list[dict] = []
    evidence_links: list[dict] = []
    for row in rows:
        claim_type, confidence = classify_chat_message(row["content"])
        claim_id = stable_id("clm", "msg", str(row["id"]), target_date, claim_type)
        evidence_id = stable_id("evd", "msg", str(row["id"]))
        title = row["content"].splitlines()[0].strip()[:80]
        claim_packets.append(
            {
                "claim_id": claim_id,
                "claim_type": claim_type,
                "title": title or f"chat-message-{row['id']}",
                "content": row["content"],
                "confidence": confidence,
                "source_kind": "chat_message",
                "source_ref": {
                    "message_id": row["id"],
                    "agent_type": row["agent_type"],
                    "project_path": row["project_path"],
                    "timestamp": row["timestamp"],
                },
                "source_date": target_date,
            }
        )
        evidence_links.append(
            {
                "claim_id": claim_id,
                "evidence_id": evidence_id,
                "evidence_type": "human_assertion",
                "source_table": "messages",
                "source_id": row["id"],
            }
        )
    return claim_packets, evidence_links


def build_promotion_suggestions(claim_packets: list[dict]) -> list[dict]:
    counts = {"daily": 0, "adr": 0, "card": 0}
    for claim in claim_packets:
        claim_type = claim["claim_type"]
        if claim_type == "decision":
            counts["adr"] += 1
        elif claim_type in {"action", "open_loop"}:
            counts["daily"] += 1
        elif claim_type in {"fact", "risk", "insight_candidate"}:
            counts["card"] += 1
    suggestions = []
    for candidate_type, count in counts.items():
        if count <= 0:
            continue
        suggestions.append(
            {
                "candidate_type": candidate_type,
                "count": count,
                "reason": f"{count} claims matched the default {candidate_type} promotion path.",
            }
        )
    return suggestions


def build_claim_packet(target_date: str, include_chat: bool = True) -> dict:
    if not DB_PATH.exists():
        return {
            "target_date": target_date,
            "include_chat": include_chat,
            "claim_packets": [],
            "evidence_links": [],
            "promotion_suggestions": [],
        }

    conn = get_db_connection()
    try:
        source_claims, source_evidence = fetch_source_claims(conn, target_date)
        chat_claims, chat_evidence = fetch_chat_claims(conn, target_date) if include_chat else ([], [])
    finally:
        conn.close()

    claim_packets = source_claims + chat_claims
    evidence_links = source_evidence + chat_evidence
    return {
        "target_date": target_date,
        "include_chat": include_chat,
        "claim_packets": claim_packets,
        "evidence_links": evidence_links,
        "promotion_suggestions": build_promotion_suggestions(claim_packets),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract typed knowledge claims into JSON packets.")
    parser.add_argument("target_date")
    parser.add_argument("--skip-chat", action="store_true")
    parser.add_argument("--output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    packet = build_claim_packet(args.target_date, include_chat=not args.skip_chat)
    rendered = json.dumps(packet, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
