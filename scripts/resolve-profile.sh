#!/usr/bin/env bash
# resolve-profile.sh: Resolves the machine's mac-bootstrap profile (e.g. home/work)
#
# Resolution hierarchy:
# 1. $MAC_BOOTSTRAP_PROFILE environment variable
# 2. $PRIVATE_DIR/current_profile (local untracked override)
# 3. $PRIVATE_DIR/machines.json (by hardware UUID or hostname)
# 4. Interactive prompt (if stdin is a TTY and machines.json exists, saves to machines.json)
# 5. default_profile in machines.json (or fallback: work)
# 6. Legacy $PRIVATE_DIR/profile fallback

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Locate private dir
if [ -n "${MAC_BOOTSTRAP_PRIVATE_DIR:-}" ] && [ -d "$MAC_BOOTSTRAP_PRIVATE_DIR" ]; then
  PRIVATE_DIR="$MAC_BOOTSTRAP_PRIVATE_DIR"
elif [ -d "$TEMPLATE_DIR/../private" ]; then
  PRIVATE_DIR="$(cd "$TEMPLATE_DIR/../private" && pwd)"
elif [ -d "$TEMPLATE_DIR/private" ]; then
  PRIVATE_DIR="$(cd "$TEMPLATE_DIR/private" && pwd)"
else
  PRIVATE_DIR=""
fi

# 1. Environment variable
if [ -n "${MAC_BOOTSTRAP_PROFILE:-}" ]; then
  echo "$MAC_BOOTSTRAP_PROFILE"
  exit 0
fi

# Helper: Get Hardware UUID
get_hardware_uuid() {
  if command -v ioreg >/dev/null 2>&1; then
    ioreg -d2 -c IOPlatformExpertDevice 2>/dev/null | awk -F'"' '/IOPlatformUUID/{print $4}' | tr -d '[:space:]' || true
  fi
}

# Helper: Get Hostname
get_local_hostname() {
  local h=""
  if command -v scutil >/dev/null 2>&1; then
    h="$(scutil --get LocalHostName 2>/dev/null || true)"
  fi
  if [ -z "$h" ]; then
    h="$(hostname -s 2>/dev/null || true)"
  fi
  echo "$h" | tr -d '[:space:]'
}

# 2. Local override file
if [ -n "$PRIVATE_DIR" ] && [ -f "$PRIVATE_DIR/current_profile" ]; then
  local_prof="$(tr -d '[:space:]' < "$PRIVATE_DIR/current_profile")"
  if [ -n "$local_prof" ]; then
    echo "$local_prof"
    exit 0
  fi
fi

MACHINES_JSON=""
if [ -n "$PRIVATE_DIR" ] && [ -f "$PRIVATE_DIR/machines.json" ]; then
  MACHINES_JSON="$PRIVATE_DIR/machines.json"
fi

HW_UUID="$(get_hardware_uuid)"
HOST_NAME="$(get_local_hostname)"

# 3. Match from machines.json
if [ -n "$MACHINES_JSON" ] && command -v jq >/dev/null 2>&1; then
  matched_profile=""
  # Try UUID first
  if [ -n "$HW_UUID" ]; then
    matched_profile="$(jq -r --arg uuid "$HW_UUID" '.machines[$uuid].profile // empty' "$MACHINES_JSON" 2>/dev/null || true)"
  fi
  # Try Hostname next
  if [ -z "$matched_profile" ] && [ -n "$HOST_NAME" ]; then
    matched_profile="$(jq -r --arg host "$HOST_NAME" '
      (.machines[$host].profile) //
      ([.machines[] | select(.hostname == $host) | .profile][0]) //
      empty
    ' "$MACHINES_JSON" 2>/dev/null || true)"
  fi

  if [ -n "$matched_profile" ]; then
    echo "$matched_profile"
    exit 0
  fi
fi

# 4. Interactive prompt if new/unregistered machine and stdin is a TTY
if [ -t 0 ] && [ -n "$MACHINES_JSON" ] && command -v jq >/dev/null 2>&1 && [ -n "$HW_UUID" ]; then
  echo "=== New machine detected ===" >&2
  echo "UUID:     $HW_UUID" >&2
  echo "Hostname: $HOST_NAME" >&2
  echo "Please select profile for this machine:" >&2
  echo "  1) home (skips work chat, work docs)" >&2
  echo "  2) work (skips entertainment/streaming)" >&2
  read -r -p "Enter choice [1/2, default: 1]: " choice </dev/tty || choice=""

  chosen="home"
  case "$choice" in
    2|work)
      chosen="work"
      ;;
    *)
      chosen="home"
      ;;
  esac

  # Save to machines.json
  today="$(date +%Y-%m-%d)"
  tmp_json="$(mktemp "${MACHINES_JSON}.tmp.XXXXXX")"
  jq --arg uuid "$HW_UUID" --arg host "$HOST_NAME" --arg prof "$chosen" --arg date "$today" '
    .machines[$uuid] = {
      "hostname": $host,
      "profile": $prof,
      "updated_at": $date
    }
  ' "$MACHINES_JSON" > "$tmp_json" && mv "$tmp_json" "$MACHINES_JSON"

  echo "Registered machine $HOST_NAME ($HW_UUID) as '$chosen' in $MACHINES_JSON" >&2
  echo "$chosen"
  exit 0
fi

# 5. Default profile from machines.json
if [ -n "$MACHINES_JSON" ] && command -v jq >/dev/null 2>&1; then
  def_profile="$(jq -r '.default_profile // empty' "$MACHINES_JSON" 2>/dev/null || true)"
  if [ -n "$def_profile" ]; then
    echo "$def_profile"
    exit 0
  fi
fi

# 6. Legacy fallback: private/profile or default "work"
if [ -n "$PRIVATE_DIR" ] && [ -f "$PRIVATE_DIR/profile" ]; then
  legacy_prof="$(tr -d '[:space:]' < "$PRIVATE_DIR/profile")"
  if [ -n "$legacy_prof" ]; then
    echo "$legacy_prof"
    exit 0
  fi
fi

echo "work"
