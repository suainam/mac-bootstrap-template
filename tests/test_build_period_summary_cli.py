from __future__ import annotations

import sys
from pathlib import Path


DATA_HUB_DIR = Path(__file__).resolve().parent.parent / "agent" / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import build_period_summary


def test_build_period_summary_cli_accepts_daily(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["build_period_summary.py", "--level", "daily", "--anchor-date", "2026-07-10"],
    )

    args = build_period_summary.parse_args()

    assert args.level == "daily"
    assert args.anchor_date == "2026-07-10"
