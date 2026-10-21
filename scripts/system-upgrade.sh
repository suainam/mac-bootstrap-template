#!/usr/bin/env bash
set -euo pipefail

ASSUME_YES=0
ONLY_STAGES=""
ONLY_EXPLICIT=0

print_usage() {
  cat <<'EOF'
Usage: scripts/system-upgrade.sh [options]

Options:
  -y, --yes          Bypass interactive TTY requirement (note: interactive prompts or sudo may still require a terminal)
      --only STAGES  Comma-separated list of stages to run (e.g. --only packages,skills)
                     Valid stages: packages, bun, uv, claude, npm, skills, chrome
  -h, --help         Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)
      ASSUME_YES=1
      shift
      ;;
    --only)
      if [[ $# -lt 2 || "$2" == -* ]]; then
        echo "Error: --only requires a non-empty stage argument" >&2
        exit 2
      fi
      ONLY_STAGES="$2"
      ONLY_EXPLICIT=1
      shift 2
      ;;
    --only=*)
      ONLY_STAGES="${1#*=}"
      ONLY_EXPLICIT=1
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      print_usage >&2
      exit 2
      ;;
  esac
done

if [[ "${MAC_BOOTSTRAP_YES:-0}" -eq 1 ]]; then
  ASSUME_YES=1
fi

VALID_STAGES=("packages" "bun" "uv" "claude" "npm" "skills" "chrome")

SELECTED_STAGES=()
if [[ "$ONLY_EXPLICIT" -eq 1 ]]; then
  # Split on commas (portable across bash 3.2+)
  saved_ifs="$IFS"
  IFS=','
  set -f
  # shellcheck disable=SC2086
  set -- $ONLY_STAGES
  IFS="$saved_ifs"
  set +f

  for s in "$@"; do
    s="$(echo "$s" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    [[ -z "$s" ]] && continue
    found=0
    for valid in "${VALID_STAGES[@]}"; do
      if [[ "$s" == "$valid" ]]; then
        found=1
        break
      fi
    done
    if [[ "$found" -eq 0 ]]; then
      echo "Error: Unknown stage '$s'. Valid stages: ${VALID_STAGES[*]}" >&2
      exit 2
    fi
    # Deduplicate repeated selections
    already_selected=0
    for prev in ${SELECTED_STAGES[@]+"${SELECTED_STAGES[@]}"}; do
      if [[ "$prev" == "$s" ]]; then
        already_selected=1
        break
      fi
    done
    if [[ "$already_selected" -eq 0 ]]; then
      SELECTED_STAGES+=("$s")
    fi
  done

  if [[ "${#SELECTED_STAGES[@]}" -eq 0 ]]; then
    echo "Error: --only must specify at least one valid stage" >&2
    exit 2
  fi
else
  SELECTED_STAGES=("${VALID_STAGES[@]}")
fi

if [[ "$ASSUME_YES" -eq 0 && (! -t 0 || ! -t 1 || ! -t 2) ]]; then
  echo "system-upgrade requires an interactive TTY; Homebrew may request sudo authentication" >&2
  exit 2
fi

export HOMEBREW_NO_UPGRADE_AUTO_UPDATES_CASKS="${HOMEBREW_NO_UPGRADE_AUTO_UPDATES_CASKS:-1}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BREW_BIN="${BREW_BIN:-$(command -v brew 2>/dev/null || echo '')}"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
SKILL_SOURCE="${SKILL_SOURCE:-}"

# --- single-instance guard -------------------------------------------------
# Two concurrent runs fight over Homebrew's own locks and download the same
# bottles twice, halving throughput. Refuse to start when the lock exists.
# No automatic stale reclaim: a run that read a dead pid could delete the lock
# a third run just created, so a leftover lock needs one manual removal.
# Lock primitives use absolute paths: tests put a fake `rm` on PATH to prove
# Homebrew locks are never deleted, and our own cleanup must not trip that.
UPGRADE_LOCK_DIR=""
UPGRADE_HEARTBEAT_PID=""

acquire_upgrade_lock() {
  local lock_dir="$1"
  local holder=""
  if /bin/mkdir "$lock_dir" 2>/dev/null; then
    UPGRADE_LOCK_DIR="$lock_dir"
    printf '%s\n' "$$" > "$lock_dir/pid"
    # A signal must stop the run too, otherwise the lock is freed while this
    # process keeps upgrading.
    trap 'stop_heartbeat; release_upgrade_lock' EXIT
    trap 'stop_heartbeat; release_upgrade_lock; exit 130' INT
    trap 'stop_heartbeat; release_upgrade_lock; exit 143' TERM
    return 0
  fi
  holder="$(/bin/cat "$lock_dir/pid" 2>/dev/null || true)"
  if [[ -n "$holder" ]]; then
    echo "Error: another system-upgrade is already running (pid ${holder})." >&2
    echo "Wait for it to finish, or stop it with: kill ${holder}" >&2
  else
    echo "Error: upgrade lock ${lock_dir} exists without a pid file." >&2
    echo "If no upgrade is running, remove it: /bin/rm -rf '${lock_dir}'" >&2
  fi
  exit 3
}

release_upgrade_lock() {
  [[ -n "${UPGRADE_LOCK_DIR:-}" ]] || return 0
  /bin/rm -rf "$UPGRADE_LOCK_DIR"
  UPGRADE_LOCK_DIR=""
}

upgrade_lock_dir() {
  local key
  key="$(printf '%s' "$1" | /usr/bin/cksum | /usr/bin/awk '{print $1}')"
  echo "${TMPDIR:-/tmp}/mac-bootstrap-system-upgrade-${key}.lock"
}

# Homebrew hides its progress bar when stdout is not a terminal, so a long
# download looks like a hang in redirected output. A detached ticker reports
# liveness; it uses /bin/sleep so PATH test doubles never drive the loop.
run_with_heartbeat() {
  local label="$1"
  shift
  if [[ -t 1 ]]; then
    "$@"
    return $?
  fi
  local interval="${UPGRADE_HEARTBEAT_SECONDS:-30}"
  local status=0
  (
    # No `local` here: this is a subshell, not a function, and macOS bash 3.2
    # rejects `local` outside one. The trap kills the in-flight sleep, so a
    # finished stage never leaves an orphan holding the output pipe.
    trap 'kill "$sleeper" 2>/dev/null; exit 0' TERM
    elapsed=0
    sleeper=""
    while :; do
      /bin/sleep "$interval" &
      sleeper=$!
      wait "$sleeper"
      elapsed=$((elapsed + interval))
      printf '  ... %s still running (%ss)\n' "$label" "$elapsed"
    done
  ) &
  UPGRADE_HEARTBEAT_PID=$!
  "$@" || status=$?
  stop_heartbeat
  return "$status"
}

stop_heartbeat() {
  [[ -n "${UPGRADE_HEARTBEAT_PID:-}" ]] || return 0
  kill "$UPGRADE_HEARTBEAT_PID" 2>/dev/null || true
  wait "$UPGRADE_HEARTBEAT_PID" 2>/dev/null || true
  UPGRADE_HEARTBEAT_PID=""
}

acquire_upgrade_lock "$(upgrade_lock_dir "$ROOT_DIR")"

# Parallel indexed arrays for Bash 3.2 compatibility
STAGE_NAMES=()
STAGE_STATUSES=()
STAGE_REASONS=()

record_stage() {
  STAGE_NAMES+=("$1")
  STAGE_STATUSES+=("$2")
  STAGE_REASONS+=("${3:-}")
}

stage_packages() {
  if [[ -z "${BREW_BIN}" || ! -x "${BREW_BIN}" ]]; then
    echo "Error: Homebrew executable not found: '${BREW_BIN}'" >&2
    record_stage "packages" "failed" "Homebrew executable not found"
    return 1
  fi
  local bundle_script="${ROOT_DIR}/scripts/brew-bundle.sh"
  if [[ ! -x "${bundle_script}" ]]; then
    echo "Error: Required script not found or not executable: ${bundle_script}" >&2
    record_stage "packages" "failed" "brew-bundle.sh missing or not executable"
    return 1
  fi

  echo "Updating Homebrew and reconciling packages from Brewfile..."
  # Retry brew update up to 3 times to handle transient CDN/network connection drops
  local update_success=0
  for attempt in 1 2 3; do
    if "${BREW_BIN}" update; then
      update_success=1
      break
    fi
    if [[ ${attempt} -lt 3 ]]; then
      echo "Warning: 'brew update' failed on attempt ${attempt}/3. Retrying in 3 seconds..." >&2
      sleep 3
    fi
  done
  
  if [[ ${update_success} -ne 1 ]]; then
    echo "Error: 'brew update' failed after 3 attempts." >&2
    record_stage "packages" "failed" "brew update failed after retries"
    return 1
  fi

  run_with_heartbeat "brew bundle install" "${bundle_script}" install && \
  run_with_heartbeat "brew upgrade" "${BREW_BIN}" upgrade || {
    echo "Error: Homebrew update/reconciliation/upgrade failed. Subsequent package steps skipped." >&2
    record_stage "packages" "failed" "package update/bundle/upgrade failed"
    return 1
  }

  "${BREW_BIN}" cleanup || {
    echo "Error: brew cleanup failed" >&2
    record_stage "packages" "failed" "brew cleanup failed"
    return 1
  }

  record_stage "packages" "success"
  return 0
}

stage_optional_cli() {
  local stage="$1"
  local bin_name="$2"
  shift 2
  local bin
  bin="$(command -v "$bin_name" 2>/dev/null || echo '')"
  if [[ -z "$bin" || ! -x "$bin" ]]; then
    echo "${bin_name} executable not found; skipping"
    record_stage "$stage" "skipped" "${bin_name} not installed"
    return 0
  fi
  if "$bin" "$@"; then
    record_stage "$stage" "success"
    return 0
  else
    echo "Error: ${bin_name} $* failed" >&2
    record_stage "$stage" "failed" "${bin_name} $* failed"
    return 1
  fi
}

stage_bun() {
  local bin
  bin="$(command -v bun 2>/dev/null || echo '')"
  if [[ -z "$bin" || ! -x "$bin" ]]; then
    echo "bun executable not found; skipping"
    record_stage "bun" "skipped" "bun not installed"
    return 0
  fi
  local out
  local status=0
  out="$("$bin" update -g 2>&1)" || status=$?
  if [[ $status -eq 0 ]]; then
    [[ -n "$out" ]] && echo "$out"
    record_stage "bun" "success"
    return 0
  elif [[ "$out" == *"No package.json"* ]]; then
    echo "No bun global packages installed; skipping"
    record_stage "bun" "skipped" "no global packages installed"
    return 0
  else
    [[ -n "$out" ]] && echo "$out" >&2
    echo "Error: bun update -g failed" >&2
    record_stage "bun" "failed" "bun update -g failed"
    return 1
  fi
}

stage_npm() {
  if ! command -v npm >/dev/null 2>&1; then
    echo "Error: npm executable not found in PATH" >&2
    record_stage "npm" "failed" "npm not installed"
    return 1
  fi
  local npm_script="${ROOT_DIR}/scripts/install-npm-global-packages.sh"
  if [[ ! -x "${npm_script}" ]]; then
    echo "Error: ${npm_script} not found or not executable" >&2
    record_stage "npm" "failed" "install-npm-global-packages.sh not executable"
    return 1
  fi

  if (cd "${ROOT_DIR}" && "${npm_script}" --yes --upgrade); then
    record_stage "npm" "success"
    return 0
  else
    echo "Error: npm global packages upgrade failed" >&2
    record_stage "npm" "failed" "npm global packages upgrade failed"
    return 1
  fi
}

stage_skills() {
  if ! command -v npx >/dev/null 2>&1; then
    echo "Error: npx not found in PATH; required for global skills update" >&2
    record_stage "skills" "failed" "npx not installed"
    return 1
  fi
  if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Error: Python executable not found: ${PYTHON_BIN}" >&2
    record_stage "skills" "failed" "Python executable not found: ${PYTHON_BIN}"
    return 1
  fi

  echo "Updating global skills via npx..."
  if ! npx --yes skills update --global; then
    echo "Error: npx skills update --global failed" >&2
    record_stage "skills" "failed" "npx skills update --global failed"
    return 1
  fi

  echo "Refreshing approved external skill bundles..."
  local update_ok=0
  if [[ -n "${SKILL_SOURCE}" ]]; then
    (cd "${ROOT_DIR}" && "${PYTHON_BIN}" scripts/skill_supply_chain.py update-bundles --source "${SKILL_SOURCE}") && update_ok=1 || true
  else
    (cd "${ROOT_DIR}" && "${PYTHON_BIN}" scripts/skill_supply_chain.py update-bundles) && update_ok=1 || true
  fi

  if [[ "$update_ok" -eq 0 ]]; then
    echo "Error: skill bundle update failed; skill distribute skipped" >&2
    record_stage "skills" "failed" "skill update-bundles failed"
    return 1
  fi

  echo "Distributing approved managed skills..."
  if ! (cd "${ROOT_DIR}" && "${PYTHON_BIN}" scripts/skill_supply_chain.py distribute); then
    echo "Error: skill distribute failed" >&2
    record_stage "skills" "failed" "skill distribute failed"
    return 1
  fi

  record_stage "skills" "success"
  return 0
}

stage_chrome() {
  echo "Patching Chrome to ensure Gemini features remain enabled..."
  if (cd "${ROOT_DIR}" && make patch-chrome-gemini); then
    record_stage "chrome" "success"
    return 0
  else
    echo "Error: make patch-chrome-gemini failed" >&2
    record_stage "chrome" "failed" "make patch-chrome-gemini failed"
    return 1
  fi
}

# Run requested stages independently
for stage in "${SELECTED_STAGES[@]}"; do
  case "$stage" in
    packages) stage_packages || true ;;
    bun)      stage_bun || true ;;
    uv)       stage_optional_cli "uv" "uv" tool upgrade --all || true ;;
    claude)   stage_optional_cli "claude" "claude" plugin marketplace update || true ;;
    npm)      stage_npm || true ;;
    skills)   stage_skills || true ;;
    chrome)   stage_chrome || true ;;
  esac
done

# Output Stage Summary Table
echo ""
echo "=========================================="
echo "         System Upgrade Summary"
echo "=========================================="

OVERALL_SUCCESS=1
FAILED_STAGES=()

i=0
while [[ $i -lt ${#STAGE_NAMES[@]} ]]; do
  name="${STAGE_NAMES[$i]}"
  status="${STAGE_STATUSES[$i]}"
  reason="${STAGE_REASONS[$i]}"
  if [[ "$status" == "success" ]]; then
    printf "  %-12s [ SUCCESS ]\n" "$name"
  elif [[ "$status" == "skipped" ]]; then
    if [[ -n "$reason" ]]; then
      printf "  %-12s [ SKIPPED ] (%s)\n" "$name" "$reason"
    else
      printf "  %-12s [ SKIPPED ]\n" "$name"
    fi
  else
    OVERALL_SUCCESS=0
    FAILED_STAGES+=("$name")
    if [[ -n "$reason" ]]; then
      printf "  %-12s [ FAILED  ] (%s)\n" "$name" "$reason"
    else
      printf "  %-12s [ FAILED  ]\n" "$name"
    fi
  fi
  i=$((i + 1))
done
echo "=========================================="

if [[ "$OVERALL_SUCCESS" -eq 1 ]]; then
  echo "All requested upgrade stages completed successfully."
  exit 0
else
  echo ""
  echo "System upgrade encountered failures in: ${FAILED_STAGES[*]}"
  FAILED_CSV=""
  for fs in "${FAILED_STAGES[@]}"; do
    if [[ -z "$FAILED_CSV" ]]; then
      FAILED_CSV="$fs"
    else
      FAILED_CSV="${FAILED_CSV},${fs}"
    fi
  done
  echo "To retry only failed stages, run:"
  if [[ "$ASSUME_YES" -eq 1 ]]; then
    echo "  MAC_BOOTSTRAP_YES=1 make system-upgrade UPGRADE_ONLY=${FAILED_CSV}"
  else
    echo "  make system-upgrade UPGRADE_ONLY=${FAILED_CSV}"
  fi
  echo ""
  echo "Note: If failures were caused by authentication or sudo timeouts, run in an interactive terminal."
  exit 1
fi
