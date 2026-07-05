from __future__ import annotations

import os
from argparse import Namespace

from lifecycle_manager_test_support import load_manager_module


def test_resolve_action_defaults_to_full_cycle_run() -> None:
    manager = load_manager_module("manager_cli_default")

    action, workflow_name, target_date = manager.resolve_action(
        Namespace(
            command=None,
            value=None,
            run=False,
            workflow="full_cycle",
            date=None,
            ingest_only=False,
            review_only=False,
            materialize_only=False,
            status=False,
            candidates=None,
            health=False,
        )
    )

    assert action == "run"
    assert workflow_name == "full_cycle"
    assert target_date


def test_resolve_action_maps_legacy_aliases() -> None:
    manager = load_manager_module("manager_cli_aliases")

    action, workflow_name, target_date = manager.resolve_action(
        Namespace(
            command=None,
            value=None,
            run=False,
            workflow="full_cycle",
            date="2026-07-01",
            ingest_only=False,
            review_only=True,
            materialize_only=False,
            status=False,
            candidates=None,
            health=False,
        )
    )

    assert (action, workflow_name, target_date) == ("run", "auto_review_only", "2026-07-01")


def test_resolve_action_supports_command_style_candidates() -> None:
    manager = load_manager_module("manager_cli_candidates")

    action, workflow_name, target_date = manager.resolve_action(
        Namespace(
            command="candidates",
            value="2026-07-02",
            run=False,
            workflow="full_cycle",
            date=None,
            ingest_only=False,
            review_only=False,
            materialize_only=False,
            status=False,
            candidates=None,
            health=False,
        )
    )

    assert action == "candidates"
    assert workflow_name is None
    assert target_date == "2026-07-02"


def test_main_delegates_run_command(monkeypatch) -> None:
    manager = load_manager_module("manager_cli_main_run")
    captured: dict[str, str] = {}

    def fake_run_workflow(workflow_name: str, target_date: str) -> None:
        captured["workflow_name"] = workflow_name
        captured["target_date"] = target_date

    monkeypatch.setattr(manager, "run_workflow", fake_run_workflow)

    manager.main(["run", "--workflow", "daily_promote_and_summary", "--date", "2026-07-03"])

    assert captured == {
        "workflow_name": "daily_promote_and_summary",
        "target_date": "2026-07-03",
    }


def test_main_delegates_status_command(monkeypatch) -> None:
    manager = load_manager_module("manager_cli_main_status")
    captured: dict[str, str] = {}

    def fake_show_status(target_date: str) -> None:
        captured["target_date"] = target_date

    monkeypatch.setattr(manager, "show_status", fake_show_status)

    manager.main(["status", "--date", "2026-07-04"])

    assert captured == {"target_date": "2026-07-04"}


def test_load_env_noops_and_preserves_explicit_environment(monkeypatch) -> None:
    manager = load_manager_module("manager_cli_load_env")
    monkeypatch.setenv("AGENT_DB_PATH", "/tmp/explicit.db")
    monkeypatch.delenv("OBSIDIAN_VAULT_DIR", raising=False)
    monkeypatch.delenv("OBSIDIAN_DAILY_DIR", raising=False)

    manager.load_env()

    assert os.environ["AGENT_DB_PATH"] == "/tmp/explicit.db"
    assert "OBSIDIAN_VAULT_DIR" not in os.environ
    assert "OBSIDIAN_DAILY_DIR" not in os.environ
