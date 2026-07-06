#!/usr/bin/env python3
"""
Agent Data Hub - Weekly Summary Script
聚合本周所有日报的 AI 总结，生成周报。
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent
if str(DATA_HUB_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_HUB_DIR))

from data_hub_config import load_prompt_template
from date_utils import get_week_range, get_year_week, is_day_before_weekend_or_holiday
from llm_filter import call_llm_raw
from obsidian_helper import read_daily, write_weekly
from db_helper import get_db_connection
from execution_logger import ExecutionLogger

# 读取环境变量
def load_env():
    return None

load_env()


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
    """调用 LLM 生成周报总结"""
    if not week_summaries:
        return "本周无日报数据。"

    daily_digests = []
    for date, summary in sorted(week_summaries.items()):
        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        daily_digests.append(f"### {date} ({day_name})\n\n{summary}")

    template = load_prompt_template("weekly-summary.md")
    if template is None:
        raise RuntimeError("Prompt template not found: weekly-summary.md")
    prompt = template.substitute(daily_digests="\n\n".join(daily_digests))

    print("[weekly_summary] 调用 LLM 生成周报...")
    result = call_llm_raw(prompt)
    return result if result else "调用 LLM 失败，未能生成周报。"


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

        if summary and "调用 LLM 失败" not in summary:
            # 构建完整周报内容
            weekly_content = f"""# {year_week} 周报

## 本周摘要

{summary}

## 每日详情

"""
            for date in sorted(week_summaries.keys()):
                day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
                weekly_content += f"### [[{date}]] ({day_name})\n\n{week_summaries[date]}\n\n"

            # 写入周报
            write_weekly(year_week, weekly_content)
            print(f"✅ 周报已写入: {year_week}.md")

            logger.complete(
                log_id,
                records_affected=len(week_summaries),
                metadata={"year_week": year_week, "days_count": len(week_summaries)},
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
