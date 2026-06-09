#!/usr/bin/env bash
# Export the latest daily drill result from Claude session JSONL into markdown.
set -euo pipefail

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

TARGET_DATE="$(date '+%Y-%m-%d')"
WAIT_SECONDS="${CLAUDE_DAILY_EXPORT_WAIT_SECONDS:-180}"
SLEEP_SECONDS="${CLAUDE_DAILY_EXPORT_SLEEP_SECONDS:-10}"
SKILL_NAME="${CLAUDE_DAILY_SKILL_NAME:-daily-claude-battle-boost}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$HOME/work}"
OUT_DIR="${CLAUDE_DAILY_EXPORT_DIR:-$PROJECT_DIR/logs/claude-daily-drill}"
LOG_DIR="${HOME}/Library/Logs/claude-daemon"
LOG="${LOG_DIR}/daily-drill-export.log"
mkdir -p "$LOG_DIR" "$OUT_DIR"

usage() {
  cat <<'EOF'
Usage: claude-daily-drill-export.sh [--date YYYY-MM-DD] [--wait-seconds N]
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --date)
      TARGET_DATE="${2:?Missing value for --date}"
      shift
      ;;
    --wait-seconds)
      WAIT_SECONDS="${2:?Missing value for --wait-seconds}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

OUT_FILE="$OUT_DIR/$TARGET_DATE.md"
TMP_FILE="$(mktemp "${TMPDIR:-/tmp}/daily-drill-export.XXXXXX")"
trap 'rm -f "$TMP_FILE"' EXIT

deadline=$(( $(date +%s) + WAIT_SECONDS ))

while [ "$(date +%s)" -le "$deadline" ]; do
  if python3 - "$TARGET_DATE" "$SKILL_NAME" "$OUT_FILE" > "$TMP_FILE" <<'PY'
import json
import sys
from pathlib import Path

target_date, skill_name, out_file = sys.argv[1], sys.argv[2], Path(sys.argv[3])
root = Path.home() / ".claude" / "projects"
prompt_marker = f"Use the `{skill_name}` skill to run today's drill."

best = None

def message_text(message):
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(part for part in parts if part).strip()
    return ""

for jsonl in root.rglob("*.jsonl"):
    try:
        lines = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]
    except Exception:
        continue
    for idx, entry in enumerate(lines):
        if entry.get("type") != "user":
            continue
        msg = entry.get("message", {})
        if msg.get("role") != "user":
            continue
        prompt_text = message_text(msg)
        if prompt_marker not in prompt_text or f"Date: {target_date}" not in prompt_text:
            continue
        for later in lines[idx + 1:]:
            if later.get("type") != "assistant":
                continue
            if later.get("attributionSkill") != skill_name:
                continue
            later_msg = later.get("message", {})
            result_text = message_text(later_msg)
            if not result_text:
                continue
            candidate = {
                "timestamp": later.get("timestamp", ""),
                "session": later.get("sessionId", ""),
                "file": str(jsonl),
                "text": result_text,
            }
            if best is None or candidate["timestamp"] > best["timestamp"]:
                best = candidate
            break

if not best:
    raise SystemExit(1)

header = [
    f"# Claude Daily Drill - {target_date}",
    "",
    f"- Skill: `{skill_name}`",
    f"- Session: `{best['session']}`",
    f"- Timestamp: `{best['timestamp']}`",
    f"- Source JSONL: `{best['file']}`",
    "",
    "---",
    "",
]

out_file.parent.mkdir(parents=True, exist_ok=True)
out_file.write_text("\n".join(header) + best["text"].rstrip() + "\n")
print(out_file)
PY
  then
    exported_path="$(cat "$TMP_FILE")"
    log "EXPORTED daily drill to ${exported_path}"
    exit 0
  fi
  sleep "$SLEEP_SECONDS"
done

log "WAIT timeout exporting daily drill for ${TARGET_DATE}"
exit 1
