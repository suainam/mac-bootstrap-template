#!/usr/bin/env python3
"""
Agent Data Hub - Ingestion Script
负责从各类 Agent 日志（Claude, Codex, AGY 等）中采集、清理并归档数据到 SQLite。
增量更新设计：使用文件的 mtime 与 DB 中已有的最新记录对比，或者无冲突插入。
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
import hashlib

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from db_helper import get_db_connection as get_shared_db_connection
from execution_logger import ExecutionLogger

# 读取环境变量
def load_env():
    env_path = Path.home() / "work/config/mac-bootstrap/private/agent/.obsidian_daily.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")

load_env()

DB_PATH = Path(os.path.expandvars(os.environ.get("AGENT_DB_PATH", str(Path.home() / "work/config/mac-bootstrap/private/agent/data/agent_history.db"))))

# Agent 数据目录
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
OPENCODE_SESSIONS_DIR = Path.home() / ".config" / "opencode" / "sessions"
CODEX_SESSIONS_DIR = OPENCODE_SESSIONS_DIR if OPENCODE_SESSIONS_DIR.exists() else Path.home() / ".codex" / "sessions"


def compute_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()

def clean_xml_tags(text: str) -> str:
    text = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", text, flags=re.DOTALL)
    text = re.sub(r"<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()

def is_system_boilerplate(text: str) -> bool:
    if "你是一名资深产品数据分析师" in text or "The user changed" in text:
        return True
    prefixes = ("# AGENTS.md", "The following is the Codex agent history", ">>> TRANSCRIPT START", "System:", "Instructions:")
    if any(text.startswith(p) for p in prefixes):
        return True
    return False

def ingest_claude(conn):
    if not CLAUDE_PROJECTS_DIR.exists(): return
    cursor = conn.cursor()
    records_count = 0
    
    for proj_dir in CLAUDE_PROJECTS_DIR.iterdir():
        user = os.environ.get("USER", "your_name")
        if not proj_dir.is_dir() or proj_dir.name in (f"-Users-{user}", "-"):
            continue
            
        for f in proj_dir.glob("*.jsonl"):
            try:
                with open(f, encoding="utf-8") as file:
                    for line in file:
                        d = json.loads(line)
                        if d.get("type") == "user":
                            msg_id = d.get("uuid")
                            ts = d.get("timestamp")
                            session_id = d.get("sessionId", f.stem)
                            
                            content_obj = d.get("message", {}).get("content", "")
                            texts = []
                            if isinstance(content_obj, list):
                                for c in content_obj:
                                    if isinstance(c, dict) and c.get("type") == "text":
                                        texts.append(c["text"])
                            elif isinstance(content_obj, str):
                                texts.append(content_obj)
                            
                            text = "\n".join(texts).strip()
                            if not text or is_system_boilerplate(text):
                                continue
                                
                            text = clean_xml_tags(text)
                            if len(text) < 5: continue
                            
                            # 插入 sessions (ignore if exists)
                            cursor.execute("""
                                INSERT OR IGNORE INTO sessions (id, agent_type, project_path, start_time, updated_at)
                                VALUES (?, ?, ?, ?, ?)
                            """, (session_id, 'claude', proj_dir.name, ts, ts))
                            
                            # 插入 messages (避免重复，用 message_id 或 hash 去重)
                            mid = msg_id or compute_hash(session_id + ts + text[:50])
                            
                            # 先检查是否已经存在
                            cursor.execute("SELECT 1 FROM messages WHERE session_id=? AND timestamp=? AND content=?", (session_id, ts, text))
                            if not cursor.fetchone():
                                cursor.execute("""
                                    INSERT INTO messages (session_id, timestamp, role, content)
                                    VALUES (?, ?, ?, ?)
                                """, (session_id, ts, 'user', text))
                                records_count += 1
            except Exception as e:
                print(f"Error parsing Claude file {f}: {e}")
    conn.commit()
    return records_count

def ingest_codex(conn):
    if not CODEX_SESSIONS_DIR.exists(): return
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
                            if isinstance(payload, dict) and payload.get("role") == "user":
                                ts = d.get("timestamp", datetime.now().isoformat())
                                session_id = f.stem
                                
                                content_obj = payload.get("content", "")
                                texts = []
                                if isinstance(content_obj, list):
                                    for c in content_obj:
                                        if isinstance(c, dict) and c.get("type") == "input_text":
                                            texts.append(c.get("text", ""))
                                elif isinstance(content_obj, str):
                                    texts.append(content_obj)
                                
                                text = "\n".join(texts).strip()
                                if not text or is_system_boilerplate(text):
                                    continue
                                    
                                if len(text) < 5 or text.startswith("<skill>"): continue
                                
                                cursor.execute("""
                                    INSERT OR IGNORE INTO sessions (id, agent_type, project_path, start_time, updated_at)
                                    VALUES (?, ?, ?, ?, ?)
                                """, (session_id, 'codex', 'Workspace', ts, ts))
                                
                                cursor.execute("SELECT 1 FROM messages WHERE session_id=? AND timestamp=? AND content=?", (session_id, ts, text))
                                if not cursor.fetchone():
                                    cursor.execute("""
                                        INSERT INTO messages (session_id, timestamp, role, content)
                                        VALUES (?, ?, ?, ?)
                                    """, (session_id, ts, 'user', text))
                                    records_count += 1
            except Exception as e:
                print(f"Error parsing Codex file {f}: {e}")
    conn.commit()
    return records_count

def ingest_agy(conn):
    AGY_BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"
    if not AGY_BRAIN_DIR.exists(): return
    cursor = conn.cursor()
    records_count = 0
    
    for sid in AGY_BRAIN_DIR.iterdir():
        transcript = sid / ".system_generated" / "logs" / "transcript.jsonl"
        if not transcript.exists(): continue
        
        session_id = sid.name
        try:
            with open(transcript, encoding="utf-8") as file:
                for line in file:
                    d = json.loads(line)
                    t = d.get("type", "")
                    if t == "USER_INPUT":
                        ts = d.get("created_at", datetime.now().isoformat())
                        content = d.get("content", "")
                        
                        text = clean_xml_tags(content)
                        if not text or is_system_boilerplate(text) or len(text) < 10:
                            continue
                            
                        cursor.execute("""
                            INSERT OR IGNORE INTO sessions (id, agent_type, project_path, start_time, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                        """, (session_id, 'agy', 'AGY Workspace', ts, ts))
                        
                        cursor.execute("SELECT 1 FROM messages WHERE session_id=? AND content=?", (session_id, text))
                        if not cursor.fetchone():
                            cursor.execute("""
                                INSERT INTO messages (session_id, timestamp, role, content)
                                VALUES (?, ?, ?, ?)
                            """, (session_id, ts, 'user', text))
                            records_count += 1
        except Exception as e:
            print(f"Error parsing AGY file {transcript}: {e}")
    conn.commit()
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
