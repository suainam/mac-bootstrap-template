#!/usr/bin/env python3
"""
Generate candidate review items from extracted external-source items and write a
daily review queue markdown file into the Obsidian vault.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from candidate_review_io import render_candidate_markdown, stable_candidate_id
from candidate_store import (
    fetch_candidates,
    iter_source_rows,
    prune_stale_candidates,
    upsert_candidates,
)
from db_helper import get_db_connection as get_shared_db_connection
from execution_logger import ExecutionLogger


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


def main() -> None:
    target_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_shared_db_connection()
    logger = ExecutionLogger(conn, target_date)

    log_id = logger.start("generate_candidates")
    try:
        prune_stale_candidates(conn)
        changed = upsert_candidates(conn, target_date, iter_source_rows(conn, target_date), stable_candidate_id)
        rows = fetch_candidates(conn, target_date)

        out_path = CANDIDATE_DIR / f"{target_date}.md"
        out_path.write_text(render_candidate_markdown(target_date, rows), encoding="utf-8")
        print(f"[generate_candidates] {target_date}: {len(changed)} upserted, {len(rows)} candidates -> {out_path}")

        logger.complete(log_id, records_affected=len(changed))
    except Exception as e:
        logger.fail(log_id, str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
