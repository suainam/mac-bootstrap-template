"""Obsidian vault helper for reading and writing notes."""
from __future__ import annotations

import os
import re
from pathlib import Path


def get_vault_dir() -> Path:
    """Get Obsidian vault directory from env."""
    return Path(
        os.path.expandvars(os.environ.get("OBSIDIAN_VAULT_DIR", str(Path.home() / "work/knowledge")))
    )


def get_daily_dir() -> Path:
    """Get daily notes directory."""
    vault = get_vault_dir()
    daily_subdir = os.environ.get("OBSIDIAN_DAILY_DIR", "10_Periodic/Daily")
    return vault / daily_subdir


def read_daily(date: str) -> str:
    """Read daily note content for given date."""
    daily_dir = get_daily_dir()
    daily_path = daily_dir / f"{date}.md"
    if not daily_path.exists():
        return ""
    return daily_path.read_text(encoding="utf-8")


def write_daily_section(date: str, section_title: str, content: str):
    """Write or replace a section in daily note."""
    daily_dir = get_daily_dir()
    daily_path = daily_dir / f"{date}.md"
    if not daily_path.exists():
        raise FileNotFoundError(f"Daily note not found: {daily_path}")

    text = daily_path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(^## {re.escape(section_title)}\n)(.*?)(^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match:
        new_text = pattern.sub(rf"\1{content}\n\n\3", text, count=1)
    else:
        new_text = text.rstrip() + f"\n\n## {section_title}\n\n{content}\n"

    daily_path.write_text(new_text, encoding="utf-8")


def read_weekly(year_week: str) -> str:
    """Read weekly note content for given year-week (e.g., '2026-W27')."""
    vault = get_vault_dir()
    weekly_dir = vault / "10_Periodic" / "Weekly"
    weekly_path = weekly_dir / f"{year_week}.md"
    if not weekly_path.exists():
        return ""
    return weekly_path.read_text(encoding="utf-8")


def write_weekly(year_week: str, content: str):
    """Write weekly note."""
    vault = get_vault_dir()
    weekly_dir = vault / "10_Periodic" / "Weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    weekly_path = weekly_dir / f"{year_week}.md"
    weekly_path.write_text(content, encoding="utf-8")
