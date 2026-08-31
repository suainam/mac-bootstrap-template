#!/usr/bin/env bash
# =============================================================================
# macOS Adaptive TCP Network Tuning & Profile Manager
# Purpose: Dynamically size and persist environment-specific TCP tuning (home/office/etc)
# Usage: ./scripts/net-tune-macos.sh [status|probe|tune|save|apply|auto|list|restore] [PROFILE] [--apply]
# =============================================================================

set -euo pipefail

ACTION="${1:-tune}"
PROFILE_ARG="${2:-}"
APPLY_FLAG="${3:-}"

CONFIG_DIR="${HOME}/.config/mac-bootstrap"
PROFILE_FILE="${CONFIG_DIR}/net-profiles.json"
mkdir -p "$CONFIG_DIR"

# macOS Kernel Upper Hard-Limits
MAX_ALLOWED_SOCKBUF=16777216

init_or_migrate_profiles() {
  if [ ! -f "$PROFILE_FILE" ]; then
    cat <<EOF > "$PROFILE_FILE"
{
  "profiles": {
    "home": {
      "name": "Home (1G Down / 160M Up / 235ms RTT)",
      "target_up_mbps": 160,
      "target_down_mbps": 1000,
      "target_rtt_ms": 235,
      "sendspace": 4194304,
      "recvspace": 8388608,
      "autosndbufmax": 16777216,
      "autorcvbufmax": 16777216,
      "maxsockbuf": 16777216,
      "networks": []
    },
    "office": {
      "name": "Office Default",
      "target_up_mbps": 100,
      "target_down_mbps": 500,
      "target_rtt_ms": 200,
      "sendspace": 2097152,
      "recvspace": 4194304,
      "autosndbufmax": 8388608,
      "autorcvbufmax": 16777216,
      "maxsockbuf": 16777216,
      "networks": []
    },
    "mobile": {
      "name": "Mobile Hotspot / Low Latency",
      "target_up_mbps": 30,
      "target_down_mbps": 100,
      "target_rtt_ms": 100,
      "sendspace": 524288,
      "recvspace": 1048576,
      "autosndbufmax": 4194304,
      "autorcvbufmax": 8388608,
      "maxsockbuf": 16777216,
      "networks": []
    }
  },
  "current_active": "stock"
}
EOF
  else
    # Auto-sanitize any profile exceeding macOS 16MB ceiling
    python3 -c "
import json
try:
    data = json.load(open('${PROFILE_FILE}'))
    modified = False
    for p in data.get('profiles', {}).values():
        if p.get('maxsockbuf', 0) > ${MAX_ALLOWED_SOCKBUF}:
            p['maxsockbuf'] = ${MAX_ALLOWED_SOCKBUF}
            modified = True
        if p.get('autorcvbufmax', 0) > ${MAX_ALLOWED_SOCKBUF}:
            p['autorcvbufmax'] = ${MAX_ALLOWED_SOCKBUF}
            modified = True
        if 'ssids' in p and 'networks' not in p:
            p['networks'] = p.pop('ssids')
            modified = True
    if modified:
        json.dump(data, open('${PROFILE_FILE}', 'w'), indent=2)
except Exception:
    pass
" 2>/dev/null || true
  fi
}

init_or_migrate_profiles

# Defaults
DEFAULT_SENDSPACE=131072
DEFAULT_RECVSPACE=131072
DEFAULT_AUTOSNDBUFMAX=4194304
DEFAULT_AUTORCVBUFMAX=4194304
DEFAULT_MAXSOCKBUF=8388608

get_sysctl() {
  local key="$1"
  sysctl -n "$key" 2>/dev/null || echo "0"
}

get_current_network_identifier() {
  local identifier=""

  # 1. Try system_profiler SPAirPortDataType for Wi-Fi SSID
  identifier=$(system_profiler SPAirPortDataType 2>/dev/null | awk '/Current Network Information:/ {getline; gsub(/^ +|:$/,""); print; exit}' || true)

  # 2. Try airport tool if non-empty
  if [ -z "$identifier" ]; then
    identifier=$(/System/Library/PrivateFrameworks/Apple80211.framework/Resources/airport -I 2>/dev/null | awk -F': ' '/ SSID/ {print $2}' || true)
  fi

  # 3. Fall back to a gateway IP signature (e.g. gw:<gateway-ip>)
  if [ -z "$identifier" ]; then
    local gw
    gw=$(route -n get default 2>/dev/null | awk '/gateway:/ {print $2}' || true)
    if [ -n "$gw" ]; then
      identifier="gw:${gw}"
    fi
  fi

  echo "${identifier:-unknown}"
}

show_status() {
  echo "=== Current macOS TCP Socket Parameters ==="
  echo "  net.inet.tcp.sendspace:        $(get_sysctl net.inet.tcp.sendspace) bytes ($(awk "BEGIN {printf \"%.2f KB\", $(get_sysctl net.inet.tcp.sendspace)/1024}"))"
  echo "  net.inet.tcp.recvspace:        $(get_sysctl net.inet.tcp.recvspace) bytes ($(awk "BEGIN {printf \"%.2f KB\", $(get_sysctl net.inet.tcp.recvspace)/1024}"))"
  echo "  net.inet.tcp.autosndbufmax:    $(get_sysctl net.inet.tcp.autosndbufmax) bytes ($(awk "BEGIN {printf \"%.2f MB\", $(get_sysctl net.inet.tcp.autosndbufmax)/(1024*1024)}"))"
  echo "  net.inet.tcp.autorcvbufmax:    $(get_sysctl net.inet.tcp.autorcvbufmax) bytes ($(awk "BEGIN {printf \"%.2f MB\", $(get_sysctl net.inet.tcp.autorcvbufmax)/(1024*1024)}"))"
  echo "  kern.ipc.maxsockbuf:           $(get_sysctl kern.ipc.maxsockbuf) bytes ($(awk "BEGIN {printf \"%.2f MB\", $(get_sysctl kern.ipc.maxsockbuf)/(1024*1024)}"))"
  echo "  net.inet.tcp.win_scale_factor: $(get_sysctl net.inet.tcp.win_scale_factor)"
  echo "  Current Network Signature:     $(get_current_network_identifier)"
}

list_profiles() {
  echo "=== Saved Network Profiles (${PROFILE_FILE}) ==="
  python3 -c "
import json
data = json.load(open('${PROFILE_FILE}'))
profiles = data.get('profiles', {})
for k, v in profiles.items():
    print(f'* [{k}] {v.get(\"name\", k)}')
    print(f'    Target: {v.get(\"target_up_mbps\")}M Up / {v.get(\"target_down_mbps\")}M Down ({v.get(\"target_rtt_ms\")}ms RTT)')
    print(f'    Values: sendspace={v.get(\"sendspace\")//1024}KB, recvspace={v.get(\"recvspace\")//1024}KB, autosndbufmax={v.get(\"autosndbufmax\")//(1024*1024)}MB, maxsockbuf={v.get(\"maxsockbuf\")//(1024*1024)}MB')
    if v.get('networks'):
        print(f'    Associated Networks/SSIDs: {\", \".join(v.get(\"networks\"))}')
"
}

probe_network() {
  local target="${TARGET_HOST:-cc15}"
  echo "=== Probing Network Environment (${target}) ==="

  local ping_out
  ping_out=$(ping -c 5 -W 2 "$target" 2>&1 || true)
  local rtt
  rtt=$(echo "$ping_out" | awk -F'/' '/rtt|round-trip/ {print $5}' || echo "0")
  rtt="${rtt:-230}"

  if (( $(echo "$rtt < 1.0" | bc -l 2>/dev/null || echo 1) )); then
    echo "  [INFO] Local proxy/tun detected (ping RTT ${rtt}ms). Using target physical baseline RTT (235ms)."
    rtt="235"
  fi
  echo "  Measured / Estimated RTT: ${rtt} ms"

  PROBED_RTT="$rtt"
}

calculate_tuning() {
  local up_mbps="${TARGET_UP_MBPS:-160}"
  local down_mbps="${TARGET_DOWN_MBPS:-1000}"
  local rtt_ms="${TARGET_RTT_MS:-${PROBED_RTT:-235}}"

  echo "=== Dynamic BDP Calculation ==="
  echo "  Target Uplink:   ${up_mbps} Mbps"
  echo "  Target Downlink: ${down_mbps} Mbps"
  echo "  Target RTT:      ${rtt_ms} ms"

  local calculated_sendspace
  calculated_sendspace=$(python3 -c "
up = float('$up_mbps') * 1e6 / 8.0
rtt = float('$rtt_ms') / 1000.0
raw = int(up * rtt * 1.5)
val = max(524288, min(raw, 4194304))
print(int((val + 65535) // 65536 * 65536))
")

  local calculated_recvspace
  calculated_recvspace=$(python3 -c "
down = float('$down_mbps') * 1e6 / 8.0
rtt = float('$rtt_ms') / 1000.0
raw = int(down * rtt * 1.5)
val = max(1048576, min(raw, 8388608))
print(int((val + 65535) // 65536 * 65536))
")

  local autosndbufmax=$(( calculated_sendspace * 4 ))
  if [ "$autosndbufmax" -lt 8388608 ]; then autosndbufmax=8388608; fi
  if [ "$autosndbufmax" -gt "$MAX_ALLOWED_SOCKBUF" ]; then autosndbufmax="$MAX_ALLOWED_SOCKBUF"; fi

  local autorcvbufmax=$(( calculated_recvspace * 2 ))
  if [ "$autorcvbufmax" -lt "$MAX_ALLOWED_SOCKBUF" ]; then autorcvbufmax="$MAX_ALLOWED_SOCKBUF"; fi
  if [ "$autorcvbufmax" -gt "$MAX_ALLOWED_SOCKBUF" ]; then autorcvbufmax="$MAX_ALLOWED_SOCKBUF"; fi

  local maxsockbuf="$MAX_ALLOWED_SOCKBUF"

  echo ""
  echo "  Calculated Parameters (Clamped to macOS ${MAX_ALLOWED_SOCKBUF}B ceiling):"
  echo "    net.inet.tcp.sendspace:     ${calculated_sendspace} bytes ($(awk "BEGIN {printf \"%.2f MB\", ${calculated_sendspace}/(1024*1024)}"))"
  echo "    net.inet.tcp.recvspace:     ${calculated_recvspace} bytes ($(awk "BEGIN {printf \"%.2f MB\", ${calculated_recvspace}/(1024*1024)}"))"
  echo "    net.inet.tcp.autosndbufmax: ${autosndbufmax} bytes ($(awk "BEGIN {printf \"%.2f MB\", ${autosndbufmax}/(1024*1024)}"))"
  echo "    net.inet.tcp.autorcvbufmax: ${autorcvbufmax} bytes ($(awk "BEGIN {printf \"%.2f MB\", ${autorcvbufmax}/(1024*1024)}"))"
  echo "    kern.ipc.maxsockbuf:        ${maxsockbuf} bytes ($(awk "BEGIN {printf \"%.2f MB\", ${maxsockbuf}/(1024*1024)}"))"

  NEW_SENDSPACE="$calculated_sendspace"
  NEW_RECVSPACE="$calculated_recvspace"
  NEW_AUTOSNDBUFMAX="$autosndbufmax"
  NEW_AUTORCVBUFMAX="$autorcvbufmax"
  NEW_MAXSOCKBUF="$maxsockbuf"
}

save_profile() {
  local pname="${PROFILE_ARG:-home}"
  local current_net
  current_net=$(get_current_network_identifier)

  probe_network
  calculate_tuning

  python3 -c "
import json
data = json.load(open('${PROFILE_FILE}'))
profiles = data.setdefault('profiles', {})
networks = profiles.get('${pname}', {}).get('networks', [])
if '${current_net}' != 'unknown' and '${current_net}' not in networks:
    networks.append('${current_net}')

profiles['${pname}'] = {
    'name': '${pname} Profile',
    'target_up_mbps': int('${TARGET_UP_MBPS:-160}'),
    'target_down_mbps': int('${TARGET_DOWN_MBPS:-1000}'),
    'target_rtt_ms': int(round(float('${PROBED_RTT:-235}'))),
    'sendspace': int('${NEW_SENDSPACE}'),
    'recvspace': int('${NEW_RECVSPACE}'),
    'autosndbufmax': int('${NEW_AUTOSNDBUFMAX}'),
    'autorcvbufmax': int('${NEW_AUTORCVBUFMAX}'),
    'maxsockbuf': int('${NEW_MAXSOCKBUF}'),
    'networks': networks
}
json.dump(data, open('${PROFILE_FILE}', 'w'), indent=2)
print(f'✅ Profile \"${pname}\" saved with network association: {networks}')
"
}

apply_named_profile() {
  local pname="${PROFILE_ARG:-home}"
  echo "=== Loading Network Profile: [${pname}] ==="

  local script
  script=$(python3 -c "
import json, sys
data = json.load(open('${PROFILE_FILE}'))
p = data.get('profiles', {}).get('${pname}')
if not p:
    print(f'Error: Profile \"${pname}\" not found in ${PROFILE_FILE}', file=sys.stderr)
    sys.exit(1)
print(f'sudo sysctl net.inet.tcp.sendspace={p[\"sendspace\"]} net.inet.tcp.recvspace={p[\"recvspace\"]} net.inet.tcp.autosndbufmax={p[\"autosndbufmax\"]} net.inet.tcp.autorcvbufmax={p[\"autorcvbufmax\"]} kern.ipc.maxsockbuf={p[\"maxsockbuf\"]}')
")

  echo "Executing: ${script}"
  eval "$script"
  echo "✅ Profile [${pname}] applied successfully."
}

auto_detect_and_apply() {
  local current_net
  current_net=$(get_current_network_identifier)
  echo "=== Auto-Detecting Network Profile (Network Signature: ${current_net}) ==="

  local matched_profile
  matched_profile=$(python3 -c "
import json
data = json.load(open('${PROFILE_FILE}'))
net = '${current_net}'
matched = None
for k, v in data.get('profiles', {}).items():
    if net in v.get('networks', []):
        matched = k
        break
print(matched or '')
")

  if [ -n "$matched_profile" ]; then
    echo "Found matching profile for network '${current_net}': [${matched_profile}]"
    PROFILE_ARG="$matched_profile"
    apply_named_profile
  else
    echo "No matching profile for network '${current_net}'. Falling back to default 'home' profile (or run 'make net-tune-save PROFILE=name' to bind)."
    PROFILE_ARG="home"
    apply_named_profile
  fi
}

restore_defaults() {
  echo "=== Restoring macOS Stock TCP Defaults ==="
  sudo sysctl net.inet.tcp.sendspace="$DEFAULT_SENDSPACE" \
    net.inet.tcp.recvspace="$DEFAULT_RECVSPACE" \
    net.inet.tcp.autosndbufmax="$DEFAULT_AUTOSNDBUFMAX" \
    net.inet.tcp.autorcvbufmax="$DEFAULT_AUTORCVBUFMAX" \
    kern.ipc.maxsockbuf="$DEFAULT_MAXSOCKBUF"
  echo "✅ Restored macOS stock network defaults."
}

case "$ACTION" in
  status|show)
    show_status
    ;;
  list|ls)
    list_profiles
    ;;
  probe)
    probe_network
    ;;
  save)
    save_profile
    ;;
  apply|load)
    apply_named_profile
    ;;
  auto)
    auto_detect_and_apply
    ;;
  restore|reset)
    restore_defaults
    ;;
  tune)
    if [ -n "$PROFILE_ARG" ] && [ "$PROFILE_ARG" != "--apply" ]; then
      apply_named_profile
    else
      show_status
      echo ""
      probe_network
      calculate_tuning
      if [ "$APPLY_FLAG" = "--apply" ] || [ "$PROFILE_ARG" = "--apply" ]; then
        echo ""
        sudo sysctl net.inet.tcp.sendspace="$NEW_SENDSPACE" \
          net.inet.tcp.recvspace="$NEW_RECVSPACE" \
          net.inet.tcp.autosndbufmax="$NEW_AUTOSNDBUFMAX" \
          net.inet.tcp.autorcvbufmax="$NEW_AUTORCVBUFMAX" \
          kern.ipc.maxsockbuf="$NEW_MAXSOCKBUF"
        echo "✅ Tuning applied successfully."
      else
        echo ""
        echo "To apply, run: make net-tune-apply (or make net-tune PROFILE=home)"
      fi
    fi
    ;;
  *)
    echo "Usage: $0 [status|probe|tune|save|apply|auto|list|restore] [PROFILE] [--apply]"
    exit 1
    ;;
esac
