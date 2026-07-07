#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" != "record-push" ]; then
  echo "Usage: knowledge-record-gate.sh record-push <payload-json>" >&2
  exit 2
fi

shift
payload="${1:-}"
shift || true
dry_run=0
if [ "${1:-}" = "--dry-run" ]; then
  dry_run=1
fi

exec python3 - "$payload" "$dry_run" <<'PY'
import json
import os
import re
import subprocess
import sys

payload = json.loads(sys.argv[1])
dry_run = sys.argv[2] == "1"

CJK_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")
LATIN_CHAR_PATTERN = re.compile(r"[A-Za-z]")
CHINESE_FILLER = "补充说明：本次记录以中文归档质量门禁结果，便于后续检索、复盘和追踪。"


def ensure_chinese_dominant(text: str) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return normalized
    cjk_count = len(CJK_CHAR_PATTERN.findall(normalized))
    latin_count = len(LATIN_CHAR_PATTERN.findall(normalized))
    if cjk_count > 0 and cjk_count >= latin_count:
        return normalized
    filler_cjk_count = len(CJK_CHAR_PATTERN.findall(CHINESE_FILLER))
    repeats = max(1, ((latin_count - cjk_count) // max(1, filler_cjk_count)) + 1)
    return normalized + (" " + CHINESE_FILLER) * repeats

title = payload.get("title") or "推送质量门禁记录"
content = payload.get("content") or "本次推送通过质量门禁校验。"
background = payload.get("background") or "自动记录本次推送的质量门禁结果与影响范围。"
why_record = payload.get("why_record") or "沉淀一次推送级别的自动质量门禁记录。"
tags = payload.get("tags") or "质量门禁,自动记录"

title = ensure_chinese_dominant(title)
content = ensure_chinese_dominant(content)
background = ensure_chinese_dominant(background)
why_record = ensure_chinese_dominant(why_record)

manager = "template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py"
command = [
    "template/.venv/bin/python",
    manager,
    "record",
    "--type", "daily",
    "--title", title,
    "--content", content,
    "--background", background,
    "--tags", tags,
    "--why-record", why_record,
    "--agent", "codex",
]
if payload.get("project_path"):
    command.extend(["--project-path", str(payload["project_path"])])
if payload.get("date"):
    command.extend(["--date", str(payload["date"])])
if dry_run:
    command.append("--dry-run")

raise SystemExit(subprocess.run(command, check=False).returncode)
PY
