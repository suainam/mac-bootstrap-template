from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
from pathlib import Path

import pytest

from helpers import AGENT_SKILLS


TEMPLATE_ROOT = Path(__file__).parent.parent
MANAGER_PATH = AGENT_SKILLS / "local" / "global" / "knowledge-lifecycle-manager" / "scripts" / "manager.py"


def load_manager_module(module_name: str = "manager_under_test"):
    spec = importlib.util.spec_from_file_location(module_name, MANAGER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def temp_manager_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = Path(temp_file.name)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS execution_log (
            id TEXT PRIMARY KEY,
            execution_date TEXT NOT NULL,
            step_name TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
            records_affected INTEGER,
            error_message TEXT,
            metadata_json TEXT,
            UNIQUE(execution_date, step_name, started_at)
        );

        CREATE TABLE IF NOT EXISTS knowledge_candidates (
            id TEXT PRIMARY KEY,
            candidate_date TEXT NOT NULL,
            candidate_type TEXT NOT NULL,
            status TEXT NOT NULL,
            confidence REAL NOT NULL
        );
        """
    )
    conn.commit()

    yield conn

    conn.close()
    db_path.unlink()
