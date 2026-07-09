from __future__ import annotations

import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent / "agent" / "data-hub"
sys.path.insert(0, str(DATA_HUB_DIR))

import data_hub_config
import summary_inputs


def configure_runtime(monkeypatch, tmp_path: Path) -> Path:
    vault_dir = tmp_path / "knowledge"
    runtime = tmp_path / "private" / "agent" / "data_hub.runtime.jsonc"
    runtime.parent.mkdir(parents=True)
    monkeypatch.setattr(data_hub_config, "RUNTIME_CONFIG", runtime)
    monkeypatch.setenv("OBSIDIAN_VAULT_DIR", str(vault_dir))
    return vault_dir


def test_required_daily_dates_respects_deployment_start_and_workdays():
    dates = summary_inputs.required_summary_dates(
        "weekly",
        "2026-07-06",
        "2026-07-12",
        "2026-07-10",
    )

    assert dates == ["2026-07-10"]


def test_previous_level_mapping():
    assert summary_inputs.previous_level("weekly") == "daily"
    assert summary_inputs.previous_level("monthly") == "weekly"
    assert summary_inputs.previous_level("quarterly") == "monthly"
    assert summary_inputs.previous_level("yearly") == "quarterly"


def test_missing_previous_layer_uses_expected_lower_periods(monkeypatch, tmp_path: Path):
    vault_dir = configure_runtime(monkeypatch, tmp_path)
    daily_dir = vault_dir / "70_Summaries" / "Daily"
    daily_dir.mkdir(parents=True)
    (daily_dir / "2026-07-10.md").write_text("# Daily Summary 2026-07-10\n", encoding="utf-8")

    missing = summary_inputs.missing_previous_layer(
        "weekly",
        "2026-07-06",
        "2026-07-12",
        "2026-07-10",
    )

    assert missing == []


def test_expected_previous_layer_sources_are_bounded_to_period(monkeypatch, tmp_path: Path):
    vault_dir = configure_runtime(monkeypatch, tmp_path)
    daily_dir = vault_dir / "70_Summaries" / "Daily"
    daily_dir.mkdir(parents=True)
    (daily_dir / "2026-07-10.md").write_text("# Daily Summary 2026-07-10\n", encoding="utf-8")
    (daily_dir / "2026-07-13.md").write_text("# Daily Summary 2026-07-13\n", encoding="utf-8")

    sources = summary_inputs.previous_layer_sources(
        "weekly",
        "2026-07-06",
        "2026-07-12",
        "2026-07-10",
    )

    assert sources == [
        {
            "source_kind": "daily_summary",
            "source_ref": "70_Summaries/Daily/2026-07-10.md",
            "metadata": {"period_id": "2026-07-10", "content": "# Daily Summary 2026-07-10\n"},
        }
    ]


def test_monthly_previous_periods_skip_open_week():
    periods = summary_inputs.required_previous_periods(
        "monthly",
        "2026-08-01",
        "2026-08-31",
        "2026-08-01",
    )

    assert periods == [
        ("weekly", "2026-08-01", "2026-W31"),
        ("weekly", "2026-08-03", "2026-W32"),
        ("weekly", "2026-08-10", "2026-W33"),
        ("weekly", "2026-08-17", "2026-W34"),
        ("weekly", "2026-08-24", "2026-W35"),
    ]
