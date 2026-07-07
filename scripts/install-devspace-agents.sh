#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOOTSTRAP="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$BOOTSTRAP/.." && pwd)"
TARGET_DIR="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
PYTHON="${PYTHON:-$BOOTSTRAP/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

LABELS=(
  "io.local.mac-bootstrap.devspace"
  "io.local.mac-bootstrap.devspace-tunnel"
)

TEMPLATES=(
  "$BOOTSTRAP/launchd/io.local.mac-bootstrap.devspace.plist"
  "$BOOTSTRAP/launchd/io.local.mac-bootstrap.devspace-tunnel.plist"
)

target_plist_for_label() {
  local label="$1"
  printf '%s/%s.plist\n' "$TARGET_DIR" "$label"
}

json_value() {
  local expr="$1"
  "$PYTHON" -c '
import json
import sys

data = json.load(sys.stdin)
expr = sys.argv[1]
current = data
for part in expr.split("."):
    current = current[part]
print(current)
' "$expr"
}

effective_config() {
  (cd "$BOOTSTRAP" && ./scripts/devspace-local.sh print-config)
}

log_dir() {
  effective_config | json_value "runtime.log_dir"
}

public_base_url() {
  effective_config | json_value "exposure.public_base_url"
}

render_template() {
  local template="$1"
  local target="$2"
  local logs="$3"
  sed \
    -e "s|{{BOOTSTRAP}}|$BOOTSTRAP|g" \
    -e "s|{{REPO_ROOT}}|$REPO_ROOT|g" \
    -e "s|{{LOG_DIR}}|$logs|g" \
    "$template" > "$target"
}

install_one() {
  local label="$1"
  local template="$2"
  local target
  target="$(target_plist_for_label "$label")"

  render_template "$template" "$target" "$(log_dir)"
  plutil -lint "$target" >/dev/null

  launchctl bootout "$DOMAIN" "$target" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$target"
  launchctl enable "$DOMAIN/$label"
  launchctl kickstart -k "$DOMAIN/$label"
  echo "Installed launch agent: $target"
}

install_agents() {
  local logs
  logs="$(log_dir)"
  mkdir -p "$TARGET_DIR" "$logs"
  install_one "${LABELS[0]}" "${TEMPLATES[0]}"
  install_one "${LABELS[1]}" "${TEMPLATES[1]}"
}

unload_agents() {
  local label target
  for label in "${LABELS[@]}"; do
    target="$(target_plist_for_label "$label")"
    launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
    launchctl bootout "$DOMAIN" "$target" 2>/dev/null || true
    rm -f "$target"
    echo "Unloaded launch agent: $label"
  done
}

status_agents() {
  local label url
  for label in "${LABELS[@]}"; do
    echo "=== $label ==="
    launchctl print "$DOMAIN/$label" 2>/dev/null || echo "not loaded"
  done
  echo "=== DevSpace local health ==="
  (cd "$BOOTSTRAP" && ./scripts/devspace-local.sh doctor) || true
  url="$(public_base_url || true)"
  if [[ -n "$url" ]]; then
    echo "PUBLIC URL: $url/mcp"
  fi
}

tail_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    echo "=== $path ==="
    tail -n 80 "$path"
  else
    echo "=== $path ==="
    echo "missing"
  fi
}

logs_agents() {
  local logs
  logs="$(log_dir)"
  tail_file "$logs/launchd-devspace.stdout.log"
  tail_file "$logs/launchd-devspace.stderr.log"
  tail_file "$logs/devspace.stdout.log"
  tail_file "$logs/devspace.stderr.log"
  tail_file "$logs/launchd-tunnel.stdout.log"
  tail_file "$logs/launchd-tunnel.stderr.log"
}

restart_agents() {
  local label
  for label in "${LABELS[@]}"; do
    launchctl kickstart -k "$DOMAIN/$label"
    echo "Restarted launch agent: $label"
  done
}

usage() {
  cat <<'EOF'
Usage: scripts/install-devspace-agents.sh install|unload|status|logs|restart
EOF
}

case "${1:-}" in
  install)
    install_agents
    ;;
  unload)
    unload_agents
    ;;
  status)
    status_agents
    ;;
  logs)
    logs_agents
    ;;
  restart)
    restart_agents
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
