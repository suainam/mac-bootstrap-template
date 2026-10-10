#!/usr/bin/env bash
set -euo pipefail

# System health patrol & auto-remediation agent
# Checks for:
# 1. Runaway user log files (> threshold MB) and auto-rotates them safely.
# 2. Crash reports, Jetsam kills, and CPU throttle alerts in the last 24h.
# 3. Failing / non-zero LaunchAgents/Daemons.
# 4. Root disk capacity >= 90%.
# 5. Potential macOS unified log storms.
#
# Notifications:
# If issues are found and --notify (or running from launchd) is set, displays
# a native macOS notification alert. Exits silently when all checks pass.

QUIET=false
DRY_RUN=false
NOTIFY=false
STRICT=false
SKIP_CLEANUP=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --quiet)
      QUIET=true
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    --notify)
      NOTIFY=true
      ;;
    --strict)
      STRICT=true
      ;;
    --skip-cleanup)
      SKIP_CLEANUP=true
      ;;
    -h|--help)
      cat <<'EOF'
Usage: system-patrol.sh [--quiet] [--dry-run] [--notify] [--strict]

Options:
  --quiet    Suppress healthy output; print only alerts.
  --dry-run  Simulate actions without rotating files.
  --notify   Send a macOS desktop notification if any faults are found.
  --strict        Exit with non-zero code if any faults are found.
  --skip-cleanup  Skip disk and cache cleanup routines.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done

# Test injection overrides
LOGS_DIR="${SYSTEM_PATROL_LOGS_DIR:-$HOME/Library/Logs}"
DIAG_USER="${SYSTEM_PATROL_DIAG_USER:-$HOME/Library/Logs/DiagnosticReports}"
DIAG_SYS="${SYSTEM_PATROL_DIAG_SYSTEM:-/Library/Logs/DiagnosticReports}"
MAX_LOG_MB="${SYSTEM_PATROL_MAX_LOG_MB:-15}"
NOTIFY_CMD="${SYSTEM_PATROL_NOTIFY_CMD:-osascript}"
LAUNCHCTL_CMD="${SYSTEM_PATROL_LAUNCHCTL_CMD:-launchctl}"
DF_CMD="${SYSTEM_PATROL_DF_CMD:-df}"

ALERTS=()
REMEDIATIONS=()

# -------------------------------------------------------------
# 0. Routine Maintenance & Disk Hygiene (Cleanup)
# -------------------------------------------------------------
if [ "${SYSTEM_PATROL_SKIP_CLEANUP:-false}" != "true" ] && [ "$SKIP_CLEANUP" = false ]; then
  # 0.1 Empty user Trash
  if [ -d "$HOME/.Trash" ]; then
    trash_count="$(find "$HOME/.Trash" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ' || echo 0)"
    if [ "$trash_count" -gt 0 ]; then
      if [ "$DRY_RUN" = true ]; then
        REMEDIATIONS+=("Would empty ~/.Trash (${trash_count} items)")
      else
        rm -rf "$HOME/.Trash"/* 2>/dev/null || true
        REMEDIATIONS+=("Emptied ~/.Trash (${trash_count} items cleared)")
      fi
    fi
  fi

  # 0.2 Package manager caches
  if [ "$DRY_RUN" = false ]; then
    if command -v uv >/dev/null 2>&1; then
      uv cache prune --quiet 2>/dev/null || true
    fi
    if command -v brew >/dev/null 2>&1; then
      brew cleanup -s --quiet 2>/dev/null || true
    fi

    # 0.3 Bun & npm cache
    if [ -d "$HOME/.bun/install/cache" ]; then
      rm -rf "$HOME/.bun/install/cache"/* 2>/dev/null || true
      REMEDIATIONS+=("Cleaned ~/.bun/install/cache")
    fi
    if command -v npm >/dev/null 2>&1; then
      npm cache clean --force >/dev/null 2>&1 || true
      REMEDIATIONS+=("Cleaned npm cache")
    fi

    # 0.4 Docker system prune (if daemon reachable)
    if command -v docker >/dev/null 2>&1; then
      if docker info >/dev/null 2>&1; then
        prune_reclaimed="$(docker system prune -f 2>&1 | grep -i "reclaimed space:" | tr -d '\n' || true)"
        if [ -n "$prune_reclaimed" ]; then
          REMEDIATIONS+=("Docker prune: ${prune_reclaimed}")
        fi
      fi
    fi

    # 0.5 Clean macOS 4K aerial screensaver video caches
    WALLPAPER_VIDEOS_DIR="$HOME/Library/Application Support/com.apple.wallpaper/aerials/videos"
    if [ -d "$WALLPAPER_VIDEOS_DIR" ]; then
      video_count="$(find "$WALLPAPER_VIDEOS_DIR" -type f 2>/dev/null | wc -l | tr -d ' ' || echo 0)"
      if [ "$video_count" -gt 0 ]; then
        rm -rf "${WALLPAPER_VIDEOS_DIR:?}"/* 2>/dev/null || true
        REMEDIATIONS+=("Cleaned 4K aerial wallpaper video cache (${video_count} videos removed)")
      fi
    fi
  fi
fi

# -------------------------------------------------------------
# 1. Runaway log file auto-remediation
# -------------------------------------------------------------
if [ -d "$LOGS_DIR" ]; then
  while IFS= read -r -d '' logfile; do
    [ -f "$logfile" ] || continue
    # Get file size in MB
    size_bytes="$(wc -c < "$logfile" 2>/dev/null | tr -d ' ' || echo 0)"
    size_mb="$((size_bytes / 1048576))"
    if [ "$size_mb" -ge "$MAX_LOG_MB" ]; then
      if [ "$DRY_RUN" = true ]; then
        REMEDIATIONS+=("Would rotate $(basename "$logfile") (${size_mb}MB >= ${MAX_LOG_MB}MB)")
      else
        tmp_file="${logfile}.tmp.$$"
        if tail -n 2000 "$logfile" > "$tmp_file" 2>/dev/null && cat "$tmp_file" > "$logfile" 2>/dev/null; then
          rm -f "$tmp_file" 2>/dev/null || true
          REMEDIATIONS+=("Auto-rotated $(basename "$logfile") (was ${size_mb}MB, kept last 2000 lines)")
        else
          rm -f "$tmp_file" 2>/dev/null || true
          ALERTS+=("Failed to rotate runaway log $(basename "$logfile") (${size_mb}MB)")
        fi
      fi
    fi
  done < <(find "$LOGS_DIR" -maxdepth 2 -type f \( -name "*.log" -o -name "*.err" \) -size "+${MAX_LOG_MB}M" -print0 2>/dev/null || true)
fi

# -------------------------------------------------------------
# 2. Crash reports & resource warnings in last 24 hours
# -------------------------------------------------------------
RECENT_REPORTS=()
for diag_dir in "$DIAG_USER" "$DIAG_SYS"; do
  [ -d "$diag_dir" ] || continue
  while IFS= read -r -d '' rpt; do
    [ -f "$rpt" ] || continue
    base="$(basename "$rpt")"
    case "$base" in
      *.ips|*.cpu_resource.diag|*.gpu_resource.diag)
        RECENT_REPORTS+=("$base")
        ;;
    esac
  done < <(find "$diag_dir" -maxdepth 1 -type f -mtime -1 -print0 2>/dev/null || true)
done

if [ "${#RECENT_REPORTS[@]}" -gt 0 ]; then
  # Deduplicate summary of processes
  sample_reports="$(printf '%s\n' "${RECENT_REPORTS[@]}" | head -n 3 | paste -sd, - || true)"
  if [ "${#RECENT_REPORTS[@]}" -gt 3 ]; then
    sample_reports="${sample_reports} (+$((${#RECENT_REPORTS[@]} - 3)) more)"
  fi
  ALERTS+=("Found ${#RECENT_REPORTS[@]} crash/resource reports in last 24h: ${sample_reports}")
fi

# -------------------------------------------------------------
# 3. Failing launchd services
# -------------------------------------------------------------
FAILING_SERVICES=()
if command -v "$LAUNCHCTL_CMD" >/dev/null 2>&1; then
  while IFS=$'\t' read -r pid status label; do
    [ "$status" = "0" ] && continue
    [ "$status" = "-" ] && continue
    [ "$status" = "Status" ] && continue

    # If PID is a running process, the service is currently alive (status is just historical last-exit)
    if [ "$pid" != "-" ] && kill -0 "$pid" 2>/dev/null; then
      continue
    fi

    # Ignore negative signal terminations (e.g. -9 SIGKILL on idle/unload)
    if [[ "$status" =~ ^-[0-9]+$ ]]; then
      continue
    fi

    # Flag dead services with non-zero exit codes
    FAILING_SERVICES+=("${label} (exit ${status})")
  done < <("$LAUNCHCTL_CMD" list 2>/dev/null || true)
fi

if [ "${#FAILING_SERVICES[@]}" -gt 0 ]; then
  svc_sample="$(printf '%s\n' "${FAILING_SERVICES[@]}" | head -n 3 | paste -sd, - || true)"
  if [ "${#FAILING_SERVICES[@]}" -gt 3 ]; then
    svc_sample="${svc_sample} (+$((${#FAILING_SERVICES[@]} - 3)) more)"
  fi
  ALERTS+=("Failing launchd services: ${svc_sample}")
fi

# -------------------------------------------------------------
# 4. Disk space guard (>= 90%)
# -------------------------------------------------------------
if command -v "$DF_CMD" >/dev/null 2>&1; then
  disk_usage="$("$DF_CMD" -k / 2>/dev/null | awk 'NR==2 {gsub(/%/, "", $5); print $5}' || echo 0)"
  if [ -n "$disk_usage" ] && [ "$disk_usage" -ge 90 ]; then
    ALERTS+=("Root volume usage is critically high (${disk_usage}%)")
  fi
fi

# -------------------------------------------------------------
# 5. Log storm quick check (optional rate check)
# -------------------------------------------------------------
if [ "${SYSTEM_PATROL_SKIP_LOG_STORM:-false}" != "true" ] && command -v log >/dev/null 2>&1; then
  if command -v timeout >/dev/null 2>&1; then
    log_rate="$(timeout 4s log show --style compact --last 1m 2>/dev/null | wc -l || echo 0)"
  else
    log_rate="$(log show --style compact --last 1m 2>/dev/null | wc -l || echo 0)"
  fi
  log_rate="$(echo "$log_rate" | tr -d ' ')"
  if [ -n "$log_rate" ] && [ "$log_rate" -ge 25000 ]; then
    ALERTS+=("Abnormally high unified log rate detected: ${log_rate} lines/min")
  fi
fi

# -------------------------------------------------------------
# Summary & Notifications
# -------------------------------------------------------------
TOTAL_FAULTS="${#ALERTS[@]}"
TOTAL_FIXES="${#REMEDIATIONS[@]}"

if [ "$TOTAL_FIXES" -gt 0 ]; then
  echo "=== System Patrol Self-Healing ==="
  for fix in "${REMEDIATIONS[@]}"; do
    echo "  * $fix"
  done
fi

if [ "$TOTAL_FAULTS" -gt 0 ]; then
  echo "=== System Patrol Alerts (${TOTAL_FAULTS}) ===" >&2
  for alert in "${ALERTS[@]}"; do
    echo "  ! $alert" >&2
  done

  if [ "$NOTIFY" = true ] && command -v "$NOTIFY_CMD" >/dev/null 2>&1; then
    # Construct concise macOS notification
    first_alert="${ALERTS[0]}"
    if [ "$TOTAL_FAULTS" -gt 1 ]; then
      detail_msg="${first_alert} 等共 ${TOTAL_FAULTS} 项异常"
    else
      detail_msg="${first_alert}"
    fi
    # Escape quotes for AppleScript
    detail_msg="${detail_msg//\"/\\\"}"
    "$NOTIFY_CMD" -e "display notification \"${detail_msg}\" with title \"macOS 系统巡检告警\" subtitle \"发现 ${TOTAL_FAULTS} 项异常需关注\" sound name \"Basso\"" 2>/dev/null || true
  fi

  if [ "$STRICT" = true ]; then
    exit 1
  fi
  exit 0
fi

if [ "$QUIET" = false ]; then
  echo "System patrol: all checks passed. System healthy."
fi
exit 0
