from __future__ import annotations

from pathlib import Path


def test_run_daily_evening_delegates_to_manager() -> None:
    script_path = Path(__file__).parent.parent / "agent" / "data-hub" / "run-daily-evening.sh"
    script_text = script_path.read_text(encoding="utf-8")

    assert "run_summary_schedule.py" in script_text
    assert "--workflow full_cycle" not in script_text
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
    assert "run --workflow build_daily_summary" in ops_text


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
    }

    for name in script_names:
        assert not (data_hub_dir / name).exists(), f"{name} should not be in data-hub root"
        assert (data_hub_dir / "scripts" / name).exists(), f"{name} should live in data-hub/scripts"


def test_legacy_summary_scripts_are_not_active_schedule_targets() -> None:
    data_hub_dir = Path(__file__).parent.parent / "agent" / "data-hub"

    assert not (data_hub_dir / "scripts" / "weekly_summary.py").exists()
    assert (data_hub_dir / "scripts" / "archive" / "weekly_summary.py").exists()
    assert "weekly_summary.py" not in (data_hub_dir / "run-daily-evening.sh").read_text(encoding="utf-8")


def test_obsidian_launchd_installer_uses_current_schedule_and_paths() -> None:
    script_path = Path(__file__).parent.parent / "launchd" / "install_obsidian_jobs.sh"
    script_text = script_path.read_text(encoding="utf-8")

    assert "REMINDER_LABEL" in script_text
    assert "<integer>9</integer>" in script_text
    assert "<integer>17</integer>" in script_text
    assert "<integer>30</integer>" in script_text
    assert "<integer>18</integer>" in script_text
    assert "<integer>30</integer>" in script_text
    assert "${DATA_HUB_DIR}/daily_morning.sh" in script_text
    assert "${DATA_HUB_DIR}/run-daily-evening.sh" in script_text
    assert "${SCRIPTS_DIR}/weekly_summary.py" not in script_text
    assert "WEEKLY_LABEL" not in script_text
    assert "${SCRIPTS_DIR}/daily_morning.sh" not in script_text
    assert "${DATA_HUB_DIR}/weekly_summary.py" not in script_text


def test_seed_periodic_templates_include_ai_summary_sections() -> None:
    templates_dir = Path(__file__).parent.parent / "editors" / "obsidian" / "vault" / "docs" / "templates"
    for name in ["daily.md", "weekly.md", "monthly.md", "quarterly.md", "yearly.md"]:
        text = (templates_dir / name).read_text(encoding="utf-8")
        assert "## AI 总结" in text

    weekly = (templates_dir / "weekly.md").read_text(encoding="utf-8")
    assert "## 本周判断" in weekly
    assert "## 自动汇总" in weekly
    assert "```dataviewjs" in weekly


def test_runtime_uses_vault_templates_before_seed_templates() -> None:
    helper_path = Path(__file__).parent.parent / "agent" / "data-hub" / "obsidian_helper.py"
    helper_text = helper_path.read_text(encoding="utf-8")

    assert 'vault_dir / "00_System" / "Templates"' in helper_text
    assert "if vault_template.exists()" in helper_text
