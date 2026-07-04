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
    ops_path = Path(__file__).parent.parent / "agent" / "data-hub" / "ops.md"

    readme_text = readme_path.read_text(encoding="utf-8")
    ops_text = ops_path.read_text(encoding="utf-8")

    assert "knowledge-lifecycle-manager" in readme_text
    assert "统一入口" in readme_text
    assert "manager.py" in ops_text
    assert "run --workflow full_cycle" in ops_text
