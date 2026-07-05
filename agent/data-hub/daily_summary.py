#!/usr/bin/env python3
"""
Agent Data Hub - Daily Summary Script
从 SQLite 读取今天的 Agent 日志和 Git log，生成 AI 总结，并更新 Obsidian 日报。
此脚本将替代原本的 product_strategy/scripts/daily_evening.py。
"""

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from source_dates import document_matches_target
from data_hub_config import get_runtime_config
from db_helper import get_db_connection as get_shared_db_connection
from execution_logger import ExecutionLogger
from obsidian_helper import ensure_daily_note, get_daily_dir, write_daily_section

# 读取环境变量
def load_env():
    return None

load_env()

RUNTIME_CONFIG = get_runtime_config()
OBSIDIAN_VAULT_DIR = RUNTIME_CONFIG.paths.vault_dir
DAILY_DIR = get_daily_dir()
GIT_SEARCH_ROOTS = RUNTIME_CONFIG.paths.git_search_roots
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("TZ", "Asia/Shanghai"))
BARE_SUMMARY_TAG_RE = re.compile(r"(?<![\w/#-])#(?:绩效|成长|复盘)(?![/\\-])(?=\s|$|[，。；、,.!?])")
HIERARCHICAL_SUMMARY_TAG_RE = re.compile(r"#(绩效|成长|复盘)/([\w\u4e00-\u9fff]+)")
BACKTICKED_SUMMARY_TAG_RE = re.compile(r"`(#(?:绩效|成长|复盘)[-/][\w\u4e00-\u9fff]+)`")


def get_runtime_python() -> str:
    venv_python = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable

def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def get_daily_file(date_str: str) -> Path:
    return DAILY_DIR / f"{date_str}.md"


def message_belongs_to_local_date(timestamp: str, target_date: str) -> bool:
    normalized = timestamp.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return timestamp.startswith(target_date)
    if dt.tzinfo is None:
        return dt.date().isoformat() == target_date
    return dt.astimezone(LOCAL_TIMEZONE).date().isoformat() == target_date

def get_git_logs(target_date: str) -> list[str]:
    """收集指定目录下的 git 提交"""
    commits = []
    author = os.environ.get("USER", "your_name")
    for root in GIT_SEARCH_ROOTS:
        if not root.exists():
            continue
        for repo in root.iterdir():
            if not repo.is_dir() or not (repo / ".git").exists():
                continue
            try:
                cmd = [
                    "git", "log",
                    f"--since={target_date} 00:00:00",
                    f"--until={target_date} 23:59:59",
                    f"--author={author}",
                    "--oneline", "--no-merges"
                ]
                res = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=False)
                if res.returncode == 0 and res.stdout.strip():
                    commits.append(f"**{repo.name}**\n" + "\n".join([f"- {line}" for line in res.stdout.strip().split("\n")]))
            except Exception as e:
                print(f"[daily_summary] 读取 git log 失败 {repo}: {e}", file=sys.stderr)
    return commits

def get_agent_logs_from_db(target_date: str) -> str:
    """从 SQLite 中提取今天的 Agent 会话"""
    conn = get_shared_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT s.agent_type, s.id as session_id, s.project_path, m.timestamp, m.content
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
            WHERE m.role = 'user'
            ORDER BY m.timestamp ASC
            """
        )
        rows = [row for row in cursor.fetchall() if message_belongs_to_local_date(row["timestamp"], target_date)]
        if not rows:
            return ""

        session_map: dict[str, dict[str, object]] = {}
        for row in rows:
            sid = row["session_id"]
            if sid not in session_map:
                session_map[sid] = {
                    "agent_type": row["agent_type"],
                    "project": row["project_path"],
                    "questions": [],
                }

            content = row["content"]
            questions = session_map[sid]["questions"]
            assert isinstance(questions, list)
            if not any(content[:50] == question[:50] for question in questions):
                if len(questions) < 5:
                    questions.append(content)

        out = []
        for sid, data in session_map.items():
            agent = str(data["agent_type"]).capitalize()
            proj = str(data["project"])
            user = os.environ.get("USER", "your_name")
            if proj.startswith(f"-Users-{user}"):
                proj = proj.replace(f"-Users-{user}-work-projects-", "").replace(f"-Users-{user}-work-", "").replace("-", "/")
            questions = data["questions"]
            assert isinstance(questions, list)
            out.append(
                f"### {agent} ({proj})\n"
                + "\n".join(f"- {question[:300].replace(chr(10), ' ')}" for question in questions)
            )

        return "\n\n".join(out)
    finally:
        conn.close()


def get_external_source_digest(target_date: str) -> str:
    """从 SQLite 中提取指定日期的外部材料候选项"""
    conn = get_shared_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT d.source_type, d.title AS document_title, d.path, d.version_tag, d.captured_at, d.metadata_json,
                   i.item_type, i.title, i.content
            FROM source_documents d
            JOIN extracted_items i ON i.document_id = d.id
            ORDER BY d.captured_at DESC, d.rowid DESC, i.rowid ASC
            LIMIT 100
            """
        )
        rows = [
            row for row in cursor.fetchall()
            if document_matches_target(
                row["path"],
                row["version_tag"],
                row["captured_at"],
                row["metadata_json"],
                target_date,
            )
        ]

        if not rows:
            return ""

        grouped = {}
        for row in rows:
            key = f"{row['source_type']} | {row['document_title']}"
            grouped.setdefault(key, [])
            grouped[key].append(f"- [{row['item_type']}] {row['title']}: {str(row['content']).replace(chr(10), ' ')[:200]}")

        out = []
        for key, lines in grouped.items():
            out.append(f"### {key}\n" + "\n".join(lines[:8]))
        return "\n\n".join(out)
    finally:
        conn.close()


def get_candidate_digest(target_date: str) -> str:
    conn = get_shared_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT candidate_type, title, status, confidence
            FROM knowledge_candidates
            WHERE candidate_date = ?
            ORDER BY candidate_type ASC, confidence DESC, rowid ASC
            LIMIT 24
            """,
            (target_date,),
        )
        rows = cursor.fetchall()
        if not rows:
            return ""

        grouped = {}
        for row in rows:
            grouped.setdefault(row["candidate_type"], [])
            grouped[row["candidate_type"]].append(
                f"- [{row['status']}] {row['title']} (confidence={float(row['confidence']):.2f})"
            )
        parts = []
        for candidate_type, lines in grouped.items():
            parts.append(f"### {candidate_type}\n" + "\n".join(lines[:8]))
        return "\n\n".join(parts)
    finally:
        conn.close()


def inject_summary_to_daily(daily_path: Path, content: str) -> None:
    """Compatibility wrapper for tests and older docs.

    Rewrites the `## AI 总结` section in-place for the provided file path.
    """
    text = daily_path.read_text(encoding="utf-8")
    pattern = re.compile(r"(^## AI 总结\s*\n)(.*?)(^## |\Z)", re.MULTILINE | re.DOTALL)
    if pattern.search(text):
        new_text = pattern.sub(rf"\1\n{content}\n\n\3", text, count=1)
    else:
        new_text = text.rstrip() + f"\n\n## AI 总结\n\n{content}\n"
    daily_path.write_text(new_text, encoding="utf-8")

def generate_summary(prompt: str) -> str:
    """通过 CLI 或 API 调用 LLM 生成总结"""
    try:
        res = subprocess.run(["agy", "-p", prompt], capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
        
    try:
        res = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
        
    return "调用 LLM 失败，未能生成总结。"


def sanitize_summary_tags(summary: str) -> str:
    """Normalize summary tags and remove broad top-level tags."""
    lines = []
    for line in summary.splitlines():
        cleaned = BACKTICKED_SUMMARY_TAG_RE.sub(r"\1", line)
        cleaned = HIERARCHICAL_SUMMARY_TAG_RE.sub(r"#\1-\2", cleaned)
        cleaned = BARE_SUMMARY_TAG_RE.sub("", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).rstrip()
        lines.append(cleaned)
    return "\n".join(lines).strip()


def build_summary_prompt(
    *,
    git_digest: str,
    agent_digest: str,
    source_digest: str,
    candidate_digest: str,
) -> str:
    tagger_path = RUNTIME_CONFIG.paths.template_root / "agent" / "skills" / "daily-tagger" / "SKILL.md"
    return f"""
基于以下信息，生成「AI 总结」节的内容，要求精炼、客观、有价值。
只输出这部分的内容（Markdown 列表形式），不要输出其他问候语或解释。

【核心要求：自动打标】
在每一条总结的末尾，请根据其内容，严格参考下面的《每日总结自动打标指南》为其自动附上对应的绩效、成长或复盘标签（可多选，没有就不加）。

必须使用指南里的完整层级标签，例如 `#绩效-计划组织`、`#绩效-专业知识`、`#成长-新贡献`、`#复盘-做得好`。
禁止使用 `#绩效`、`#成长`、`#复盘` 这类只有一级的粗标签；如果只能判断到一级，就不要打这个标签。
禁止使用 slash 形式标签，例如 `#绩效/计划组织`；统一写成 hyphen 形式 `#绩效-计划组织`，这样更适合 Dataview/搜索落地。
标签不要用反引号包裹；正确写法是 `完成验收。 #绩效-计划组织 #复盘-做得好` 这种普通 Markdown 文本。
每条总结最多 1~3 个标签，标签直接跟在句子末尾，用空格分隔。

@{tagger_path}

## Git 提交记录
{git_digest}

## AI 辅助事项 (从 Agent 会话推断)
{agent_digest or '无'}

## 外部材料候选项
{source_digest or '无'}

## 候选知识清单
{candidate_digest or '无'}
"""


def main():
    explicit_date = len(sys.argv) > 1
    target_date = sys.argv[1] if explicit_date else today_str()

    # 自动晨/晚报任务默认跳过周末；显式指定日期时允许人工补跑。
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    if dt.weekday() >= 5 and not explicit_date:
        print(f"[daily_summary] {target_date} 是周末，跳过日报总结。")
        return

    conn = get_shared_db_connection()
    logger = ExecutionLogger(conn, target_date)
    log_id = logger.start("daily_summary")

    try:
        daily_path = ensure_daily_note(target_date)
        print(f"[daily_summary] 处理日报: {daily_path}")
        if not daily_path.exists():
            raise FileNotFoundError(f"Daily note not found: {daily_path}")

        print("[daily_summary] 收集 Git 日志...")
        git_logs = get_git_logs(target_date)
        git_digest = "\n\n".join(git_logs) if git_logs else "无"

        print("[daily_summary] 收集 Agent 对话记录...")
        agent_digest = get_agent_logs_from_db(target_date)
        source_digest = get_external_source_digest(target_date)
        candidate_digest = get_candidate_digest(target_date)

        prompt = build_summary_prompt(
            git_digest=git_digest,
            agent_digest=agent_digest,
            source_digest=source_digest,
            candidate_digest=candidate_digest,
        )
        print("[daily_summary] 调用 LLM 生成总结...")
        summary = generate_summary(prompt)

        if summary and "调用 LLM 失败" not in summary:
            summary = summary.replace("## AI 总结", "").strip()
            summary = summary.lstrip("\n")
            summary = sanitize_summary_tags(summary)
            write_daily_section(target_date, "AI 总结", summary)
            print("✅ 总结已成功写入。")
            logger.complete(log_id, records_affected=1)
        else:
            print("❌ 生成总结失败。")
            logger.fail(log_id, "LLM generation failed")
    except Exception as e:
        logger.fail(log_id, str(e))
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()
