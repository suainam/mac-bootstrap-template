from __future__ import annotations

from pathlib import Path

from helpers import AGENT_SKILLS, DATA_HUB


MANAGER = AGENT_SKILLS / "local/global/knowledge-lifecycle-manager"


def test_run_daily_evening_delegates_to_manager() -> None:
    script_path = DATA_HUB / "run-daily-evening.sh"
    script_text = script_path.read_text(encoding="utf-8")

    assert "run_summary_schedule.py" in script_text
    assert "--workflow full_cycle" not in script_text
    assert "ingest_logs.py" not in script_text
    assert "materialize_candidates.py" not in script_text


def test_docs_present_manager_as_unified_entry() -> None:
    readme_path = DATA_HUB / "README.md"
    ops_path = DATA_HUB / "docs" / "ops.md"

    readme_text = readme_path.read_text(encoding="utf-8")
    ops_text = ops_path.read_text(encoding="utf-8")

    assert "knowledge-lifecycle-manager" in readme_text
    assert "统一入口" in readme_text
    assert "manager.py" in ops_text
    assert "run --workflow build_daily_summary" in ops_text


def test_docs_describe_summary_schedule_not_full_cycle() -> None:
    data_hub_dir = DATA_HUB
    readme = (data_hub_dir / "README.md").read_text(encoding="utf-8")
    ops = (data_hub_dir / "docs" / "ops.md").read_text(encoding="utf-8")
    cron = (data_hub_dir / "docs" / "archive" / "cron-setup-legacy.md").read_text(
        encoding="utf-8"
    )

    combined = "\n".join([readme, ops, cron])
    assert "build_daily_summary" in combined
    assert "70_Summaries/Daily" in combined
    assert "18:00" in combined
    assert "full_cycle" not in readme
    assert "run --workflow full_cycle" not in ops
    assert "run --workflow full_cycle" not in cron


def test_data_hub_executable_python_scripts_live_under_scripts_dir() -> None:
    data_hub_dir = DATA_HUB
    script_names = {
        "auto_review.py",
        "claim_extraction.py",
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
    data_hub_dir = DATA_HUB

    assert not (data_hub_dir / "scripts" / "weekly_summary.py").exists()
    assert (data_hub_dir / "scripts" / "archive" / "weekly_summary.py").exists()
    assert "weekly_summary.py" not in (data_hub_dir / "run-daily-evening.sh").read_text(encoding="utf-8")


def test_obsidian_launchd_installer_uses_current_schedule_and_paths() -> None:
    script_path = Path(__file__).parent.parent / "launchd" / "install_obsidian_jobs.sh"
    script_text = script_path.read_text(encoding="utf-8")

    assert 'DATA_HUB_DIR="$MAC_BOOTSTRAP_DIR/template/data-hub"' in script_text
    assert "template/agent/data-hub" not in script_text
    assert "REMINDER_LABEL" in script_text
    assert "LEGACY_WEEKLY_LABEL" in script_text
    assert "<integer>9</integer>" in script_text
    assert "<integer>17</integer>" in script_text
    assert "<integer>30</integer>" in script_text
    assert "<integer>18</integer>" in script_text
    assert "<integer>30</integer>" in script_text
    assert "${DATA_HUB_DIR}/daily_morning.sh" in script_text
    assert "${DATA_HUB_DIR}/daily_reminder.sh" in script_text
    assert "${DATA_HUB_DIR}/run-daily-evening.sh" in script_text
    assert "${SCRIPTS_DIR}/weekly_summary.py" not in script_text
    assert "weekly-summary" in script_text
    assert "18:00  自动生成" in script_text
    assert "18:30" not in script_text
    assert '\nWEEKLY_LABEL="' not in script_text
    assert "WEEKLY_PLIST" not in script_text
    assert "${SCRIPTS_DIR}/daily_morning.sh" not in script_text
    assert "${DATA_HUB_DIR}/weekly_summary.py" not in script_text


def test_troubleshooting_uses_current_evening_schedule() -> None:
    troubleshooting = (
        DATA_HUB / "docs" / "troubleshooting.md"
    ).read_text(encoding="utf-8")

    assert "晚间 summary schedule" in troubleshooting
    assert "18:00 触发" in troubleshooting
    assert "18:30" not in troubleshooting


def test_archived_cron_docs_run_summary_schedule_daily() -> None:
    cron = (DATA_HUB / "docs" / "archive" / "cron-setup-legacy.md").read_text(
        encoding="utf-8"
    )

    assert '/cron create "0 0 18 * * *"' in cron
    assert "Every day at 18:00" in cron
    assert "Every weekday at 18:00" not in cron


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
    helper_path = DATA_HUB / "obsidian_helper.py"
    helper_text = helper_path.read_text(encoding="utf-8")

    assert 'vault_dir / "00_System" / "Templates"' in helper_text
    assert "if vault_template.exists()" in helper_text
