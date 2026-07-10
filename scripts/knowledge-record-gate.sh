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
import subprocess
import sys

payload = json.loads(sys.argv[1])
dry_run = sys.argv[2] == "1"

title = payload.get("title") or "推送变更记录"
content = payload.get("content") or "本次推送未携带变更内容。"
background = payload.get("background") or "自动记录本次推送的实质性变更。"
why_record = payload.get("why_record") or "沉淀一次推送级别的真实变更记录。"
tags = payload.get("tags") or "推送记录"

manager = "template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py"
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
