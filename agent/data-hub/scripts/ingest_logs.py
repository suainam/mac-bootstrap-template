#!/usr/bin/env python3
"""
Agent Data Hub - Ingestion Script
负责从各类 Agent 日志（Claude, Codex, AGY 等）中采集、清理并归档数据到 SQLite。
增量更新设计：使用文件的 mtime 与 DB 中已有的最新记录对比，或者无冲突插入。
"""

import json
import hashlib
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent
if str(DATA_HUB_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_HUB_DIR))

from db_helper import get_db_connection as get_shared_db_connection
from data_hub_config import get_runtime_config
from execution_logger import ExecutionLogger

# 读取环境变量
def load_env():
    return None

load_env()

RUNTIME_CONFIG = get_runtime_config()
DB_PATH = RUNTIME_CONFIG.paths.db_path

# Agent 数据目录
CLAUDE_PROJECTS_DIR = RUNTIME_CONFIG.agent_logs.claude_projects_dir
OPENCODE_SESSIONS_DIR = RUNTIME_CONFIG.agent_logs.opencode_sessions_dir
CODEX_SESSIONS_DIR = RUNTIME_CONFIG.agent_logs.codex_sessions_dir
AGY_BRAIN_DIR = RUNTIME_CONFIG.agent_logs.agy_brain_dir
DEFAULT_AGY_BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"


def compute_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def clean_xml_tags(text: str) -> str:
    text = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", text, flags=re.DOTALL)
    text = re.sub(r"<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def extract_text_parts(content_obj, allowed_types: tuple[str, ...]) -> list[str]:
    """Extract human-visible text from common chat-log content shapes."""
    if isinstance(content_obj, str):
        return [content_obj]
    if not isinstance(content_obj, list):
        return []

    parts: list[str] = []
    for item in content_obj:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") in allowed_types:
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return parts


def normalize_message_text(texts: list[str], min_length: int) -> str:
    text = clean_xml_tags("\n".join(texts).strip())
    if not text or is_system_boilerplate(text) or len(text) < min_length:
        return ""
    return text


def insert_message(
    cursor: sqlite3.Cursor,
    session_id: str,
    agent_type: str,
    project_path: str,
    timestamp: str,
    role: str,
    text: str,
) -> bool:
    cursor.execute(
        """
        INSERT OR IGNORE INTO sessions (id, agent_type, project_path, start_time, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, agent_type, project_path, timestamp, timestamp),
    )
    cursor.execute(
        "SELECT 1 FROM messages WHERE session_id=? AND timestamp=? AND role=? AND content=?",
        (session_id, timestamp, role, text),
    )
    if cursor.fetchone():
        return False
    cursor.execute(
        """
        INSERT INTO messages (session_id, timestamp, role, content)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, timestamp, role, text),
    )
    return True

def is_system_boilerplate(text: str) -> bool:
    if "你是一名资深产品数据分析师" in text or "The user changed" in text:
        return True
    prefixes = ("# AGENTS.md", "The following is the Codex agent history", ">>> TRANSCRIPT START", "System:", "Instructions:")
    if any(text.startswith(p) for p in prefixes):
        return True
    return False

def ingest_claude(conn):
    if not CLAUDE_PROJECTS_DIR.exists():
        return 0
    cursor = conn.cursor()
    records_count = 0
    
    for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
        import os
        user = os.environ.get("USER", "your_name")
        if not proj_dir.is_dir() or proj_dir.name in (f"-Users-{user}", "-"):
            continue
            
        for f in proj_dir.glob("*.jsonl"):
            try:
                with open(f, encoding="utf-8") as file:
                    for line in file:
                        d = json.loads(line)
                        event_type = d.get("type")
                        if event_type in {"user", "assistant"}:
                            ts = d.get("timestamp")
                            session_id = d.get("sessionId", f.stem)
                            content_obj = d.get("message", {}).get("content", "")
                            texts = extract_text_parts(content_obj, ("text",))
                            text = normalize_message_text(texts, 5)
                            if not text:
                                continue

                            if insert_message(cursor, session_id, "claude", proj_dir.name, ts, event_type, text):
                                records_count += 1
            except Exception as e:
                print(f"Error parsing Claude file {f}: {e}")
    conn.commit()
    return records_count

def ingest_codex(conn):
    if not CODEX_SESSIONS_DIR.exists():
        return 0
    cursor = conn.cursor()
    records_count = 0
    
    # 扫描最近一年的文件夹 (结构: year/month/day/xxx.jsonl)
    for year_dir in CODEX_SESSIONS_DIR.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit(): continue
        for f in year_dir.rglob("*.jsonl"):
            try:
                with open(f, encoding="utf-8") as file:
                    for line in file:
                        d = json.loads(line)
                        if d.get("type") in ("event_msg", "response_item", "message"):
                            payload = d.get("payload", d)
                            if isinstance(payload, dict):
                                ts = d.get("timestamp", datetime.now().isoformat())
                                session_id = f.stem
                                role = payload.get("role")
                                payload_type = payload.get("type")
                                if role == "user":
                                    texts = extract_text_parts(payload.get("content", ""), ("input_text", "text"))
                                elif role == "assistant":
                                    texts = extract_text_parts(payload.get("content", ""), ("output_text", "text"))
                                elif payload_type == "agent_message":
                                    role = "assistant"
                                    message = payload.get("message", "")
                                    texts = [message] if isinstance(message, str) else []
                                else:
                                    continue

                                text = normalize_message_text(texts, 5)
                                if not text or text.startswith("<skill>"):
                                    continue

                                if insert_message(cursor, session_id, "codex", "Workspace", ts, role, text):
                                    records_count += 1
            except Exception as e:
                print(f"Error parsing Codex file {f}: {e}")
    conn.commit()
    return records_count

def ingest_agy(conn):
    agy_brain_dir = AGY_BRAIN_DIR
    if AGY_BRAIN_DIR == DEFAULT_AGY_BRAIN_DIR:
        agy_brain_dir = Path.home() / ".gemini" / "antigravity-cli" / "brain"
    if not agy_brain_dir.exists():
        return 0
    cursor = conn.cursor()
    records_count = 0
    malformed_lines = 0
    
    for sid in agy_brain_dir.iterdir():
        transcript = sid / ".system_generated" / "logs" / "transcript.jsonl"
        if not transcript.exists(): continue
        
        session_id = sid.name
        try:
            with open(transcript, encoding="utf-8") as file:
                for line in file:
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        malformed_lines += 1
                        continue
                    t = d.get("type", "")
                    if t in {"USER_INPUT", "PLANNER_RESPONSE"}:
                        ts = d.get("created_at", datetime.now().isoformat())
                        content = d.get("content", "")
                        role = "user" if t == "USER_INPUT" else "assistant"
                        if not isinstance(content, str):
                            continue

                        text = normalize_message_text([content], 10)
                        if not text:
                            continue

                        if insert_message(cursor, session_id, "agy", "AGY Workspace", ts, role, text):
                            records_count += 1
        except Exception as e:
            print(f"Error parsing AGY file {transcript}: {e}")
    conn.commit()
    if malformed_lines:
        print(f"[ingest_agy] skipped {malformed_lines} malformed AGY json lines")
    return records_count

def main():
    print("Connecting to DB:", DB_PATH)
    conn = get_shared_db_connection()
    execution_date = datetime.now().strftime("%Y-%m-%d")
    logger = ExecutionLogger(conn, execution_date)

    log_id = logger.start("ingest_logs")
    total_records = 0
    try:
        print("Ingesting Claude logs...")
        count = ingest_claude(conn)
        total_records += count
        print(f"  -> {count} new messages")

        print("Ingesting Codex logs...")
        count = ingest_codex(conn)
        total_records += count
        print(f"  -> {count} new messages")

        print("Ingesting AGY logs...")
        count = ingest_agy(conn)
        total_records += count
        print(f"  -> {count} new messages")

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages")
        total_count = cursor.fetchone()[0]
        print(f"Ingestion complete. Total messages in DB: {total_count}")

        logger.complete(log_id, records_affected=total_records)
    except Exception as e:
        logger.fail(log_id, str(e))
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()
