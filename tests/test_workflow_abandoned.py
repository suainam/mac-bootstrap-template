from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "agent" / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from mark_workflow_abandoned import mark_workflow_abandoned


def test_mark_workflow_abandoned_marks_run_and_running_steps(tmp_path):
    db_path = tmp_path / "agent.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE workflow_runs (
            id TEXT PRIMARY KEY,
            status TEXT,
            completed_at TEXT,
            error_message TEXT
        );
        CREATE TABLE workflow_steps (
            id TEXT PRIMARY KEY,
            run_id TEXT,
            status TEXT,
            completed_at TEXT,
            error_message TEXT
        );
        INSERT INTO workflow_runs (id, status) VALUES ('run_1', 'running');
        INSERT INTO workflow_steps (id, run_id, status) VALUES ('step_1', 'run_1', 'completed');
        INSERT INTO workflow_steps (id, run_id, status) VALUES ('step_2', 'run_1', 'running');
        """
    )
    conn.commit()

    mark_workflow_abandoned(conn, "run_1", "interrupted deprecated full_cycle")

    run = conn.execute("SELECT status, error_message FROM workflow_runs WHERE id='run_1'").fetchone()
    completed_step = conn.execute("SELECT status, error_message FROM workflow_steps WHERE id='step_1'").fetchone()
    running_step = conn.execute("SELECT status, error_message FROM workflow_steps WHERE id='step_2'").fetchone()
    assert run == ("failed", "interrupted deprecated full_cycle")
    assert completed_step == ("completed", None)
    assert running_step == ("failed", "interrupted deprecated full_cycle")
