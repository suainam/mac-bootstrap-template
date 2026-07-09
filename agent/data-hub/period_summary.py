from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from data_hub_config import get_runtime_config, get_summary_output_dir
from db_helper import get_db_connection
from summary_store import complete_summary_run, record_summary_sources, start_summary_run


CURRENT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = CURRENT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from knowledge_retrieval import build_retrieval_packet


LEVEL_TITLES = {
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "yearly": "Yearly",
}


def resolve_period(level: str, anchor_date: str) -> tuple[str, str, str]:
    dt = datetime.strptime(anchor_date, "%Y-%m-%d").date()
    if level == "daily":
        return dt.isoformat(), dt.isoformat(), dt.isoformat()
    if level == "weekly":
        start = dt - timedelta(days=dt.weekday())
        end = start + timedelta(days=6)
        iso = start.isocalendar()
        return f"{iso.year}-W{iso.week:02d}", start.isoformat(), end.isoformat()
    if level == "monthly":
        start = dt.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
        return f"{dt.year}-{dt.month:02d}", start.isoformat(), end.isoformat()
    if level == "quarterly":
        quarter = (dt.month - 1) // 3 + 1
        start = date(dt.year, 3 * quarter - 2, 1)
        next_quarter = date(dt.year + 1, 1, 1) if quarter == 4 else date(dt.year, 3 * quarter + 1, 1)
        end = next_quarter - timedelta(days=1)
        return f"{dt.year}-Q{quarter}", start.isoformat(), end.isoformat()
    if level == "yearly":
        start = date(dt.year, 1, 1)
        end = date(dt.year, 12, 31)
        return f"{dt.year}", start.isoformat(), end.isoformat()
    raise ValueError(f"unsupported summary level: {level}")


def extract_summary_sources(packet: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for kind, rows in packet.get("local_markdown", {}).items():
        for row in rows:
            path = str(row.get("path", ""))
            if path.startswith("70_Summaries/"):
                continue
            sources.append({"source_kind": kind, "source_ref": path, "metadata": {"score": row.get("score")}})
    for row in packet.get("open_loops", []):
        sources.append({"source_kind": "sqlite_candidate", "source_ref": row["candidate_id"], "metadata": row})
    for row in packet.get("llm_wiki_context", {}).get("results", []):
        path = str(row.get("path", ""))
        if path.startswith("70_Summaries/"):
            continue
        sources.append({"source_kind": "llm_wiki", "source_ref": path, "metadata": row})
    return sources


def render_summary_body(packet: dict[str, Any]) -> str:
    lines = ["## 重点事项", ""]
    for source_kind, rows in packet.get("local_markdown", {}).items():
        for row in rows[:5]:
            lines.append(f"- {source_kind}: {row.get('title') or row.get('path')} ({row.get('path')})")
    for row in packet.get("open_loops", [])[:5]:
        lines.append(f"- open_loop: {row.get('title')} ({row.get('candidate_id')})")
    for row in packet.get("llm_wiki_context", {}).get("results", [])[:5]:
        lines.append(f"- llm_wiki: {row.get('title') or row.get('path')} ({row.get('path')})")
    if len(lines) == 2:
        lines.append("- No matching source signals found.")

    lines.extend(["", "## 已完结", "", "- 待 llm_filter 根据证据归纳。"])
    lines.extend(["", "## 当前待办", "", "- 待 llm_filter 根据 open loops 与上下文归纳。"])
    lines.extend(["", "## 知识沉淀", ""])
    for item in packet.get("reuse_recommendations", []):
        lines.append(f"- {item}")
    if not packet.get("reuse_recommendations"):
        lines.append("- 暂无自动沉淀建议。")
    return "\n".join(lines).strip() + "\n"


def render_summary_note(level: str, period_id: str, body: str, derived_from: dict[str, list[str]]) -> str:
    return "\n".join(
        [
            "---",
            "type: summary",
            f"summary_level: {level}",
            "status: draft",
            "generated_by: data-hub",
            "indexing: excluded",
            "source_mode: daily-first",
            "derived_from:",
            "  daily:",
            *[f"    - {item}" for item in derived_from.get("daily", [])],
            "  sqlite_records:",
            *[f"    - {item}" for item in derived_from.get("sqlite_records", [])],
            "  llm_wiki_context:",
            *[f"    - {item}" for item in derived_from.get("llm_wiki_context", [])],
            "promotion_status: not_reviewed",
            "---",
            "",
            f"# {LEVEL_TITLES[level]} Summary {period_id}",
            "",
            body.strip(),
            "",
        ]
    )


def build_period_summary(level: str, anchor_date: str) -> Path:
    period_id, period_start, period_end = resolve_period(level, anchor_date)
    packet = build_retrieval_packet(
        task_goal=f"{level} summary {period_id}",
        keywords=[period_id, period_start, period_end],
        date_from=period_start,
        date_to=period_end,
        include_llm_wiki=True,
    )
    sources = extract_summary_sources(packet)
    derived_from = {
        "daily": [row["source_ref"] for row in sources if row["source_kind"] == "daily"],
        "sqlite_records": [row["source_ref"] for row in sources if row["source_kind"] == "sqlite_candidate"],
        "llm_wiki_context": [row["source_ref"] for row in sources if row["source_kind"] == "llm_wiki"],
    }
    note = render_summary_note(level, period_id, render_summary_body(packet), derived_from)
    output_dir = get_summary_output_dir(level)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{period_id}.md"
    output_path.write_text(note, encoding="utf-8")

    config = get_runtime_config()
    conn = get_db_connection()
    try:
        run_id = start_summary_run(
            conn,
            level=level,
            period_id=period_id,
            period_start=period_start,
            period_end=period_end,
            source_mode="daily-first",
        )
        record_summary_sources(conn, run_id, sources)
        complete_summary_run(
            conn,
            run_id,
            str(output_path.relative_to(config.paths.vault_dir)),
            {"source_count": len(sources), "warnings": packet.get("llm_wiki_context", {}).get("warnings", [])},
        )
    finally:
        conn.close()

    return output_path
