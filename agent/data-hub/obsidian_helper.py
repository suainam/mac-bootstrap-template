"""Obsidian vault helper for reading and writing notes."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from data_hub_config import get_runtime_config


def get_vault_dir() -> Path:
    """Get Obsidian vault directory from env."""
    return get_runtime_config().paths.vault_dir


def get_daily_dir() -> Path:
    """Get daily notes directory."""
    config = get_runtime_config()
    return config.paths.vault_dir / config.paths.daily_dir


def get_weekly_dir() -> Path:
    """Get weekly notes directory."""
    return get_vault_dir() / "10_Periodic" / "Weekly"


def _template_path(name: str) -> Path:
    config = get_runtime_config()
    vault_template = config.paths.vault_dir / "00_System" / "Templates" / name
    if vault_template.exists():
        return vault_template
    return config.paths.template_root / "editors" / "obsidian" / "vault" / "docs" / "templates" / name


def render_daily_note(date: str) -> str:
    """Render a default daily note template."""
    dt = datetime.strptime(date, "%Y-%m-%d")
    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekday_names[dt.weekday()]
    week = dt.strftime("%V")
    quarter = (dt.month - 1) // 3 + 1
    return "\n".join(
        [
            "---",
            "type: journal",
            "status: active",
            f"owner: {os.environ.get('USER', 'your_name')}",
            f"date: {date}",
            f"week: {dt.year}-W{week}",
            f"month: {dt.year}-{dt.month:02d}",
            f"quarter: {dt.year}-Q{quarter}",
            "tags: [daily, work-log]",
            "---",
            "",
            f"# {dt.year}年{dt.month:02d}月{dt.day:02d}日 {weekday}",
            "",
            "## 今日重点",
            "",
            "- [ ] ",
            "",
            "## 工作记录",
            "",
            "<!-- 周报会自动汇总本节列表项 -->",
            "",
            "## 临时需求",
            "",
            "<!-- 周报会自动汇总本节列表项 -->",
            "",
            "## 问题反馈",
            "",
            "<!-- 周报会自动汇总本节列表项 -->",
            "",
            "## 学习&思考",
            "",
            "<!-- 周报会自动汇总本节列表项 -->",
            "",
            "## AI 总结",
            "",
            "<!-- 由 Summary Engine 自动写入 70_Summaries/Daily/ -->",
            "",
            "## 明日计划",
            "",
            "- [ ] ",
            "",
            "---",
            f"关联周报：[[{dt.year}-W{week}]]",
            "",
        ]
    )


def render_weekly_note(target_date: str) -> str:
    """Render the Obsidian weekly template for target_date."""
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    week_start = dt.date().fromordinal(dt.date().toordinal() - dt.weekday())
    week_end = week_start.fromordinal(week_start.toordinal() + 6)
    year_week = f"{dt.year}-W{dt.strftime('%V')}"
    quarter = (dt.month - 1) // 3 + 1
    template = _template_path("weekly.md").read_text(encoding="utf-8")
    replacements = {
        "{{date:YYYY-[W]ww}}": year_week,
        "{{monday:YYYY-MM-DD}}": week_start.isoformat(),
        "{{sunday:YYYY-MM-DD}}": week_end.isoformat(),
        "{{date:YYYY-MM}}": f"{dt.year}-{dt.month:02d}",
        "{{date:YYYY-[Q]Q}}": f"{dt.year}-Q{quarter}",
        "{{date:YYYY}}": str(dt.year),
        "{{date:YYYY年第ww周}}": f"{dt.year}年第{dt.strftime('%V')}周",
        "{{monday:MM.DD}}": f"{week_start.month:02d}.{week_start.day:02d}",
        "{{sunday:MM.DD}}": f"{week_end.month:02d}.{week_end.day:02d}",
    }
    for old, new in replacements.items():
        template = template.replace(old, new)
    return template


def ensure_daily_note(date: str) -> Path:
    """Ensure a daily note exists and return its path."""
    daily_dir = get_daily_dir()
    daily_dir.mkdir(parents=True, exist_ok=True)
    daily_path = daily_dir / f"{date}.md"
    if not daily_path.exists():
        daily_path.write_text(render_daily_note(date), encoding="utf-8")
    return daily_path


def read_daily(date: str) -> str:
    """Read daily note content for given date."""
    daily_dir = get_daily_dir()
    daily_path = daily_dir / f"{date}.md"
    if not daily_path.exists():
        return ""
    return daily_path.read_text(encoding="utf-8")


def write_daily_section(date: str, section_title: str, content: str):
    """Write or replace a section in daily note."""
    daily_path = ensure_daily_note(date)

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
    weekly_dir = get_weekly_dir()
    weekly_path = weekly_dir / f"{year_week}.md"
    if not weekly_path.exists():
        return ""
    return weekly_path.read_text(encoding="utf-8")


def ensure_weekly_note(year_week: str, target_date: str) -> Path:
    """Ensure a weekly note exists from the Obsidian weekly template."""
    weekly_dir = get_weekly_dir()
    weekly_dir.mkdir(parents=True, exist_ok=True)
    weekly_path = weekly_dir / f"{year_week}.md"
    if not weekly_path.exists():
        weekly_path.write_text(render_weekly_note(target_date), encoding="utf-8")
    return weekly_path


def write_weekly_section(year_week: str, target_date: str, section_title: str, content: str) -> None:
    """Write or replace a section in weekly note without touching other sections."""
    weekly_path = ensure_weekly_note(year_week, target_date)
    text = weekly_path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(^## {re.escape(section_title)}\n)(.*?)(^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(text):
        new_text = pattern.sub(rf"\1\n{content}\n\n\3", text, count=1)
    else:
        new_text = text.rstrip() + f"\n\n## {section_title}\n\n{content}\n"
    weekly_path.write_text(new_text, encoding="utf-8")


def write_weekly(year_week: str, content: str):
    """Write weekly note."""
    weekly_dir = get_weekly_dir()
    weekly_dir.mkdir(parents=True, exist_ok=True)
    weekly_path = weekly_dir / f"{year_week}.md"
    weekly_path.write_text(content, encoding="utf-8")
