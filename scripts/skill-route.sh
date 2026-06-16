#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_FILE="$REPO_DIR/agent/skills-distribution.json"

usage() {
  cat <<'EOF'
Usage:
  scripts/skill-route.sh list
  scripts/skill-route.sh show <skill>
  scripts/skill-route.sh set <skill> <app1,app2,...>
  scripts/skill-route.sh clear <skill>
  scripts/skill-route.sh set-default <app1,app2,...>

Apps:
  claude,codex,opencode,pi,reasonix,antigravity,cross-agent
EOF
}

require_arg() {
  local name="$1"
  local value="${2:-}"
  if [ -z "$value" ]; then
    echo "Missing argument: $name" >&2
    usage >&2
    exit 2
  fi
}

cmd="${1:-}"
shift || true

case "$cmd" in
  list|show|set|clear|set-default)
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

python3 - "$DIST_FILE" "$cmd" "$@" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
cmd = sys.argv[2]
args = sys.argv[3:]
allowed = {
    "claude",
    "codex",
    "opencode",
    "pi",
    "reasonix",
    "antigravity",
    "cross-agent",
}

if path.exists():
    data = json.loads(path.read_text(encoding="utf-8"))
else:
    data = {"defaults": {"apps": []}, "skills": {}}

data.setdefault("defaults", {}).setdefault("apps", [])
data.setdefault("skills", {})

def parse_apps(raw: str):
    apps = [item.strip() for item in raw.split(",") if item.strip()]
    bad = [item for item in apps if item not in allowed]
    if bad:
      raise SystemExit(
          "Unknown app(s): " + ", ".join(bad) +
          ". Allowed: " + ", ".join(sorted(allowed))
      )
    return apps

if cmd == "list":
    defaults = ",".join(data["defaults"].get("apps", []))
    print(f"default={defaults}")
    for skill in sorted(data["skills"]):
        apps = ",".join(data["skills"][skill].get("apps", []))
        print(f"{skill}={apps}")
elif cmd == "show":
    if len(args) != 1:
        raise SystemExit("Usage: show <skill>")
    skill = args[0]
    apps = data["skills"].get(skill, {}).get("apps")
    if apps is None:
        apps = data["defaults"].get("apps", [])
        source = "default"
    else:
        source = "override"
    print(f"{skill} ({source}) = {','.join(apps)}")
elif cmd == "set":
    if len(args) != 2:
        raise SystemExit("Usage: set <skill> <app1,app2,...>")
    skill, raw_apps = args
    data["skills"][skill] = {"apps": parse_apps(raw_apps)}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"updated {skill}")
elif cmd == "clear":
    if len(args) != 1:
        raise SystemExit("Usage: clear <skill>")
    skill = args[0]
    data["skills"].pop(skill, None)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"cleared {skill}")
elif cmd == "set-default":
    if len(args) != 1:
        raise SystemExit("Usage: set-default <app1,app2,...>")
    data["defaults"]["apps"] = parse_apps(args[0])
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("updated defaults")
else:
    raise SystemExit(f"Unknown command: {cmd}")
PY
