#!/usr/bin/env python3
"""Auto-review candidates based on confidence thresholds."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from db_helper import get_db_connection
from execution_logger import ExecutionLogger


# Auto-review thresholds (user confirmed)
THRESHOLDS = {
    "daily": 0.8,    # action, open_loop
    "card": 0.8,     # fact, summary, topic, risk
    "adr": 0.85,     # decision
}


def load_env() -> None:
    """Load environment from .obsidian_daily.env."""
    env_path = Path.home() / "work/config/mac-bootstrap/private/agent/.obsidian_daily.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def auto_review_candidates(conn, target_date: str, logger: ExecutionLogger) -> dict:
    """Auto-review candidates by confidence threshold, update status to accepted/pending."""
    cursor = conn.execute(
        """
        SELECT id, candidate_type, confidence, status
        FROM knowledge_candidates
        WHERE candidate_date = ? AND status = 'pending'
        """,
        (target_date,),
    )
    candidates = cursor.fetchall()

    stats = {"accepted": 0, "pending": 0, "skipped": 0}

    for row in candidates:
        cand_id, cand_type, confidence, status = row
        threshold = THRESHOLDS.get(cand_type, 0.9)

        if confidence >= threshold:
            conn.execute(
                "UPDATE knowledge_candidates SET status = 'accepted' WHERE id = ?",
                (cand_id,),
            )
            stats["accepted"] += 1
        else:
            stats["pending"] += 1

    conn.commit()
    return stats


def main() -> None:
    load_env()
    target_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    logger = ExecutionLogger(conn, target_date)
    log_id = logger.start("auto_review")

    try:
        stats = auto_review_candidates(conn, target_date, logger)
        logger.complete(log_id, records_affected=stats["accepted"], metadata=stats)
        print(f"[auto_review] {target_date}: accepted={stats['accepted']}, pending={stats['pending']}")
    except Exception as e:
        logger.fail(log_id, str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

