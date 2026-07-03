#!/usr/bin/env python3
"""
Agent Data Hub - Daily Summary Script
从 SQLite 读取今天的 Agent 日志和 Git log，生成 AI 总结，并更新 Obsidian 日报。
此脚本将替代原本的 product_strategy/scripts/daily_evening.py。
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
import sqlite3

# 读取环境变量
def load_env():
    env_path = Path.home() / "work/config/mac-bootstrap/private/agent/.obsidian_daily.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")

load_env()

OBSIDIAN_VAULT_DIR = Path(os.path.expandvars(os.environ.get("OBSIDIAN_VAULT_DIR", str(Path.home() / "work/projects/product_strategy"))))
DAILY_DIR = OBSIDIAN_VAULT_DIR / "daily"
GIT_SEARCH_ROOTS = [Path(os.path.expandvars(p)) for p in os.environ.get("GIT_SEARCH_ROOTS", str(Path.home() / "work/projects")).split(",")]
DB_PATH = Path(os.path.expandvars(os.environ.get("AGENT_DB_PATH", str(Path.home() / "work/config/mac-bootstrap/private/agent/data/agent_history.db"))))

def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def get_daily_file(date_str: str) -> Path:
    return DAILY_DIR / f"{date_str}.md"

def get_git_logs(target_date: str) -> list[str]:
    """收集指定目录下的 git 提交"""
    commits = []
    author = os.environ.get("USER", "your_name")
    for root in GIT_SEARCH_ROOTS:
        if not root.exists(): continue
        for repo in root.iterdir():
            if not repo.is_dir() or not (repo / ".git").exists(): continue
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
    if not DB_PATH.exists():
        return ""
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 查找今天的消息 (UTC or Local 兼容模糊匹配)
    cursor.execute("""
        SELECT s.agent_type, s.id as session_id, s.project_path, m.content
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        WHERE m.timestamp LIKE ? AND m.role = 'user'
        ORDER BY m.timestamp ASC
    """, (f"{target_date}%",))
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return ""
        
    # 按 session_id 归类
    session_map = {}
    for row in rows:
        sid = row['session_id']
        if sid not in session_map:
            session_map[sid] = {
                'agent_type': row['agent_type'],
                'project': row['project_path'],
                'questions': []
            }
        
        content = row['content']
        # 简单去重
        if not any(content[:50] == q[:50] for q in session_map[sid]['questions']):
            if len(session_map[sid]['questions']) < 5:  # 每个 session 最多取5条
                session_map[sid]['questions'].append(content)
                
    # 格式化输出
    out = []
    for sid, data in session_map.items():
        agent = str(data['agent_type']).capitalize()
        proj = data['project']
        user = os.environ.get("USER", "your_name")
        if proj.startswith(f"-Users-{user}"):
            proj = proj.replace(f"-Users-{user}-work-projects-", "").replace(f"-Users-{user}-work-", "").replace("-", "/")
        out.append(f"### {agent} ({proj})\n" + "\n".join([f"- {q[:300].replace(chr(10), ' ')}" for q in data['questions']]))
        
    return "\n\n".join(out)

def generate_summary(prompt: str) -> str:
    """通过 CLI 或 API 调用 LLM 生成总结"""
    system_prompt = f"你是一名资深产品数据分析师的工作助理。今天是 {today_str()}。"
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

def inject_summary_to_daily(file_path: Path, summary: str) -> None:
    content = file_path.read_text()
    if "## AI 总结" not in content:
        content += f"\n## AI 总结\n\n{summary}\n"
    else:
        parts = content.split("## AI 总结")
        before = parts[0]
        after = parts[1]
        next_heading = after.find("\n## ")
        if next_heading != -1:
            after = after[next_heading:]
        else:
            after = ""
        content = f"{before}## AI 总结\n\n{summary}\n{after}"
    file_path.write_text(content)

def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else today_str()
    
    # 如果是周六、周日，直接跳过生成
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    if dt.weekday() >= 5:
        print(f"[daily_summary] {target_date} 是周末，跳过日报总结。")
        return

    daily_path = get_daily_file(target_date)
    print(f"[daily_summary] 处理日报: {daily_path}")
    if not daily_path.exists():
        print(f"[daily_summary] 警告：文件 {daily_path} 不存在。")
        return

    print("[daily_summary] 收集 Git 日志...")
    git_logs = get_git_logs(target_date)
    git_digest = "\n\n".join(git_logs) if git_logs else "无"
    
    print("[daily_summary] 收集 Agent 对话记录...")
    # 确保先入库最新数据
    ingest_script = Path(__file__).parent / "ingest_logs.py"
    if ingest_script.exists():
        subprocess.run([sys.executable, str(ingest_script)])
        
    agent_digest = get_agent_logs_from_db(target_date)
    
    prompt = f"""
基于以下信息，生成「AI 总结」节的内容，要求精炼、客观、有价值。
只输出这部分的内容（Markdown 列表形式），不要输出其他问候语或解释。

【核心要求：自动打标】
在每一条总结的末尾，请根据其内容，严格参考下面的《每日总结自动打标指南》为其自动附上对应的绩效、成长或复盘标签（可多选，没有就不加）。

@{Path.home()}/work/config/mac-bootstrap/template/agent/skills/daily-tagger/SKILL.md

## Git 提交记录
{git_digest}

## AI 辅助事项 (从 Agent 会话推断)
{agent_digest or '无'}
"""
    print("[daily_summary] 调用 LLM 生成总结...")
    summary = generate_summary(prompt)
    
    if summary and "调用 LLM 失败" not in summary:
        summary = summary.replace("## AI 总结", "").strip()
        summary = summary.lstrip("-").lstrip().lstrip("\n") # in case it outputs list without header but with some weird dashes
        inject_summary_to_daily(daily_path, summary)
        print("✅ 总结已成功写入。")
    else:
        print("❌ 生成总结失败。")

if __name__ == "__main__":
    main()
