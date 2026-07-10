#!/usr/bin/env python3
"""Archived legacy weekly writer.

Current summary automation writes to 70_Summaries via period_summary.py.
This file is preserved only for prompt and validation reference.
"""

import sys
import re
from datetime import datetime, timedelta
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent
if str(DATA_HUB_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_HUB_DIR))

from data_hub_config import load_prompt_template
from date_utils import get_week_range, get_year_week, is_day_before_weekend_or_holiday
from llm_filter import call_llm_raw
from obsidian_helper import read_daily, write_weekly_section
from db_helper import get_db_connection
from execution_logger import ExecutionLogger

# 读取环境变量
def load_env():
    return None

load_env()

MAX_WEEKLY_RETRIES = 1
WEEKLY_RETRY_INSTRUCTION = (
    "上一次输出未通过本地事实校验。请重写，并严格遵守："
    "1) 只能使用输入日报中明确出现的事实；"
    "2) 禁止新增数字、百分比、版本号、季度/里程碑结论；"
    "3) 每条必须保留依据日期，格式为（依据：YYYY-MM-DD[, YYYY-MM-DD]）；"
    "4) 若证据不足，请改写成保守描述。"
)
NUMERIC_TOKEN_RE = re.compile(r"(?:\d+(?:\.\d+)?%|Q[1-4]|V\d+(?:\.\d+)?|\d+(?:\.\d+)?)")
ASCII_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_.-]*\b")
CJK_PHRASE_RE = re.compile(r"[\u4e00-\u9fff]{2,8}")
CITATION_RE = re.compile(r"（依据：([0-9,\-、，\s]+)）\s*$")
STOP_PHRASES = {
    "本周", "工作", "事项", "问题", "总结", "推进", "跟进", "整理", "讨论", "验证", "相关",
    "完成", "优化", "技术", "方案", "能力", "流程", "配置", "系统", "模块", "支持", "生成",
}


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def extract_ai_summary_from_daily(date_str: str) -> str:
    """从日报中提取 AI 总结段落"""
    content = read_daily(date_str)
    if not content or "## AI 总结" not in content:
        return ""

    # 提取 ## AI 总结 段落
    parts = content.split("## AI 总结")
    if len(parts) < 2:
        return ""

    summary_section = parts[1]
    # 找到下一个二级标题
    next_heading = summary_section.find("\n## ")
    if next_heading != -1:
        summary_section = summary_section[:next_heading]

    return summary_section.strip()


def collect_week_summaries(start_date, end_date) -> dict[str, str]:
    """收集本周所有日报的 AI 总结"""
    summaries = {}
    current = start_date
    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        summary = extract_ai_summary_from_daily(date_str)
        if summary:
            summaries[date_str] = summary
        current += timedelta(days=1)
    return summaries


def generate_weekly_summary(week_summaries: dict[str, str]) -> str:
    """调用 LLM 生成周报总结；失败时返回空字符串供上层 fallback。"""
    if not week_summaries:
        return "本周无日报数据。"

    summary_dates = sorted(week_summaries)
    daily_digests = []
    for date, summary in sorted(week_summaries.items()):
        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        daily_digests.append(f"### {date} ({day_name})\n\n{summary}")

    template = load_prompt_template("weekly-summary.md")
    if template is None:
        raise RuntimeError("Prompt template not found: weekly-summary.md")
    # Archived helper may coexist with the structured Summary Engine prompt;
    # preserve its historical test utility without claiming it is a runtime path.
    base_prompt = template.safe_substitute(daily_digests="\n\n".join(daily_digests))

    for attempt in range(MAX_WEEKLY_RETRIES + 1):
        prompt = base_prompt if attempt == 0 else f"{base_prompt}\n\n{WEEKLY_RETRY_INSTRUCTION}"
        print("[weekly_summary] 调用 LLM 生成周报...")
        result = call_llm_raw(prompt)
        if not result:
            continue
        normalized = normalize_weekly_summary(result)
        ok, reason = validate_weekly_summary(normalized, week_summaries)
        if ok:
            return normalized
        print(f"[weekly_summary] 周报事实校验失败: {reason}")
        if attempt < MAX_WEEKLY_RETRIES:
            print("[weekly_summary] 使用更严格约束重试一次...")
    return ""


def normalize_weekly_summary(summary: str) -> str:
    summary = summary.strip()
    if summary.startswith("```"):
        lines = summary.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        summary = "\n".join(lines).strip()
    return summary


def _extract_bullets(summary: str) -> list[str]:
    return [line.strip() for line in summary.splitlines() if line.strip().startswith("- ")]


def _parse_bullet_citations(bullet: str) -> tuple[str, list[str]] | None:
    match = CITATION_RE.search(bullet)
    if not match:
        return None
    body = bullet[:match.start()].strip()
    dates = [part.strip() for part in re.split(r"[,、，]\s*", match.group(1).strip()) if part.strip()]
    return body, dates


def _collect_source_text(cited_dates: list[str], week_summaries: dict[str, str]) -> str:
    return "\n".join(week_summaries[date] for date in cited_dates if date in week_summaries)


def _has_supported_phrase(body: str, source_text: str) -> bool:
    body_ascii_tokens = ASCII_TOKEN_RE.findall(body)
    if any(token in source_text for token in body_ascii_tokens):
        return True
    for phrase in CJK_PHRASE_RE.findall(body):
        if len(phrase) < 3 or phrase in STOP_PHRASES:
            continue
        if phrase in source_text:
            return True
    body_cjk = "".join(ch for ch in body if "\u4e00" <= ch <= "\u9fff")
    source_cjk = "".join(ch for ch in source_text if "\u4e00" <= ch <= "\u9fff")
    if len(body_cjk) >= 4 and len(source_cjk) >= 4:
        body_bigrams = {body_cjk[i : i + 2] for i in range(len(body_cjk) - 1)}
        source_bigrams = {source_cjk[i : i + 2] for i in range(len(source_cjk) - 1)}
        if len(body_bigrams & source_bigrams) >= 2:
            return True
    return False


def validate_weekly_summary(summary: str, week_summaries: dict[str, str]) -> tuple[bool, str]:
    bullets = _extract_bullets(summary)
    if not 1 <= len(bullets) <= 5:
        return False, f"invalid_bullet_count:{len(bullets)}"

    available_dates = set(week_summaries)
    for bullet in bullets:
        parsed = _parse_bullet_citations(bullet)
        if parsed is None:
            return False, "missing_citation"
        body, cited_dates = parsed
        if not cited_dates or any(date not in available_dates for date in cited_dates):
            return False, f"invalid_citation_dates:{cited_dates}"
        source_text = _collect_source_text(cited_dates, week_summaries)
        if not source_text:
            return False, "empty_source_text"
        for token in NUMERIC_TOKEN_RE.findall(body):
            if token not in source_text:
                return False, f"unsupported_numeric:{token}"
        for token in ASCII_TOKEN_RE.findall(body):
            if token.lower() in {"ai", "llm", "api"}:
                continue
            if token not in source_text:
                return False, f"unsupported_ascii:{token}"
        if not _has_supported_phrase(body, source_text):
            return False, "low_source_overlap"
    return True, "ok"


def generate_fallback_weekly_summary(week_summaries: dict[str, str]) -> str:
    """Generate a deterministic weekly summary when LLM backends are unavailable."""
    if not week_summaries:
        return "本周无日报数据。"
    lines = [
        "- 本周已自动汇总现有日报 AI 总结；LLM 后端暂不可用，因此先生成本地 fallback 版周报。",
        f"- 覆盖 {len(week_summaries)} 天日报：" + "、".join(sorted(week_summaries.keys())) + "。",
        "- 重点内容请查看下方“每日详情”；外部模型恢复后可重新运行周报脚本生成归纳版摘要。",
    ]
    return "\n".join(lines)


def main():
    explicit_date = len(sys.argv) > 1
    target_date_str = sys.argv[1] if explicit_date else today_str()

    # 转换为 date 对象
    if isinstance(target_date_str, str):
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    else:
        target_date = target_date_str

    # 非显式指定时，只在周五或节前最后一个工作日执行
    if not explicit_date and not is_day_before_weekend_or_holiday(target_date):
        day_name = target_date.strftime("%A")
        print(f"[weekly_summary] {target_date} ({day_name}) 不是周五或节前，跳过周报生成。")
        return

    # 获取本周范围
    start_date, end_date = get_week_range(target_date)
    year_week = get_year_week(target_date)

    print(f"[weekly_summary] 生成周报: {year_week} ({start_date} ~ {end_date})")

    # 初始化数据库连接和日志
    conn = get_db_connection()
    logger = ExecutionLogger(conn, target_date.strftime("%Y-%m-%d"))
    log_id = logger.start("weekly_summary")

    try:
        # 收集本周日报
        print("[weekly_summary] 收集本周日报...")
        week_summaries = collect_week_summaries(start_date, end_date)

        if not week_summaries:
            print("[weekly_summary] 本周无日报数据，跳过。")
            logger.complete(log_id, metadata={"year_week": year_week, "days_count": 0})
            return

        print(f"[weekly_summary] 找到 {len(week_summaries)} 天的日报")

        # 生成周报
        summary = generate_weekly_summary(week_summaries)
        used_fallback = False

        if not summary:
            print("[weekly_summary] LLM 不可用，使用本地 fallback 周报。")
            summary = generate_fallback_weekly_summary(week_summaries)
            used_fallback = True

        if summary:
            write_weekly_section(year_week, target_date.strftime("%Y-%m-%d"), "AI 总结", summary)
            print(f"✅ 周报 AI 总结已写入: {year_week}.md")

            logger.complete(
                log_id,
                records_affected=len(week_summaries),
                metadata={
                    "year_week": year_week,
                    "days_count": len(week_summaries),
                    "fallback": used_fallback,
                },
            )
        else:
            print("❌ 生成周报失败。")
            logger.fail(log_id, "LLM 生成失败")

    except Exception as e:
        print(f"❌ 周报生成异常: {e}")
        logger.fail(log_id, str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
