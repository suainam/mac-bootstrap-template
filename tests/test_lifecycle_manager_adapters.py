from __future__ import annotations

from pathlib import Path


def test_run_daily_evening_delegates_to_manager() -> None:
    script_path = Path(__file__).parent.parent / "agent" / "data-hub" / "run-daily-evening.sh"
    script_text = script_path.read_text(encoding="utf-8")

    assert "manager.py" in script_text
    assert "--workflow full_cycle" in script_text
    assert "ingest_logs.py" not in script_text
    assert "materialize_candidates.py" not in script_text


def test_docs_present_manager_as_unified_entry() -> None:
    readme_path = Path(__file__).parent.parent / "agent" / "data-hub" / "README.md"
    ops_path = Path(__file__).parent.parent / "agent" / "data-hub" / "docs" / "ops.md"

    readme_text = readme_path.read_text(encoding="utf-8")
    ops_text = ops_path.read_text(encoding="utf-8")

    assert "knowledge-lifecycle-manager" in readme_text
    assert "统一入口" in readme_text
    assert "manager.py" in ops_text
    assert "run --workflow full_cycle" in ops_text


def test_data_hub_executable_python_scripts_live_under_scripts_dir() -> None:
    data_hub_dir = Path(__file__).parent.parent / "agent" / "data-hub"
    script_names = {
        "auto_review.py",
        "claim_extraction.py",
        "daily_summary.py",
        "generate_candidates.py",
        "health_check.py",
        "hygiene_audit.py",
        "ingest_logs.py",
        "ingest_sources.py",
        "knowledge_retrieval.py",
        "materialize_candidates.py",
        "weekly_summary.py",
    }

    for name in script_names:
        assert not (data_hub_dir / name).exists(), f"{name} should not be in data-hub root"
        assert (data_hub_dir / "scripts" / name).exists(), f"{name} should live in data-hub/scripts"
