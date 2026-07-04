from __future__ import annotations

from datetime import datetime, timedelta

from lifecycle_manager_test_support import load_manager_module, temp_manager_db


def test_show_status_no_logs(temp_manager_db, capsys, monkeypatch) -> None:
    manager = load_manager_module("manager_reporting_no_logs")
    monkeypatch.setattr(manager, "get_db_connection", lambda: temp_manager_db)
    monkeypatch.setattr(manager, "load_env", lambda: None)

    manager.show_status("2026-07-04")

    captured = capsys.readouterr()
    assert "No execution logs found for 2026-07-04" in captured.out


def test_show_candidates_grouped_by_status(temp_manager_db, capsys, monkeypatch) -> None:
    manager = load_manager_module("manager_reporting_candidates")
    temp_manager_db.execute(
        "INSERT INTO knowledge_candidates (id, candidate_date, candidate_type, status, confidence) VALUES (?, ?, ?, ?, ?)",
        ("cand_1", "2026-07-04", "card", "pending", 0.85),
    )
    temp_manager_db.execute(
        "INSERT INTO knowledge_candidates (id, candidate_date, candidate_type, status, confidence) VALUES (?, ?, ?, ?, ?)",
        ("cand_2", "2026-07-04", "card", "accepted", 0.90),
    )
    temp_manager_db.commit()

    monkeypatch.setattr(manager, "get_db_connection", lambda: temp_manager_db)
    monkeypatch.setattr(manager, "load_env", lambda: None)

    manager.show_candidates("2026-07-04")

    captured = capsys.readouterr()
    assert "Candidate Queue for 2026-07-04" in captured.out
    assert "pending" in captured.out
    assert "accepted" in captured.out


def test_health_check_with_failures(temp_manager_db, capsys, monkeypatch) -> None:
    manager = load_manager_module("manager_reporting_health")
    now = datetime.now()
    for offset in range(3):
        current = (now - timedelta(days=offset)).strftime("%Y-%m-%d")
        started_at = (now - timedelta(days=offset)).isoformat(timespec="seconds")
        temp_manager_db.execute(
            """
            INSERT INTO execution_log
                (id, execution_date, step_name, started_at, completed_at, status, records_affected, error_message, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"log-{offset}", current, f"step_{offset}", started_at, started_at, "failed", 0, f"Error {offset}", None),
        )
    temp_manager_db.commit()

    monkeypatch.setattr(manager, "get_db_connection", lambda: temp_manager_db)
    monkeypatch.setattr(manager, "load_env", lambda: None)

    manager.health_check()

    captured = capsys.readouterr()
    assert "failed steps in last 3 days" in captured.out
    assert "Error 0" in captured.out
