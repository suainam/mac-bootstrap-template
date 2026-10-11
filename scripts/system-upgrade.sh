#!/usr/bin/env bash
set -euo pipefail

ASSUME_YES=0
ONLY_STAGES=""

print_usage() {
  cat <<'EOF'
Usage: scripts/system-upgrade.sh [options]

Options:
  -y, --yes          Non-interactive mode (assumes yes for tool prompts; does not bypass sudo authentication)
      --only STAGES  Comma-separated list of stages to run
                     Valid stages: packages, bun, uv, claude, npm, skills, chrome
  -h, --help         Show this help message
EOF
}

# Parse options
while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)
      ASSUME_YES=1
      shift
      ;;
    --only)
      if [[ $# -lt 2 ]]; then
        echo "Error: --only requires a comma-separated stage list" >&2
        exit 2
      fi
      ONLY_STAGES="$2"
      shift 2
      ;;
    --only=*)
      ONLY_STAGES="${1#*=}"
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

# Validate --only stages if provided
SELECTED_STAGES=()
if [[ -n "$ONLY_STAGES" ]]; then
  IFS=',' read -r -a REQUESTED <<< "$ONLY_STAGES"
  for s in "${REQUESTED[@]}"; do
    s="$(echo "$s" | tr -d '[:space:]')"
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
    SELECTED_STAGES+=("$s")
  done
  if [[ "${#SELECTED_STAGES[@]}" -eq 0 ]]; then
    echo "Error: --only must specify at least one valid stage" >&2
    exit 2
  fi
else
  SELECTED_STAGES=("${VALID_STAGES[@]}")
fi

is_stage_selected() {
  local target="$1"
  for s in "${SELECTED_STAGES[@]}"; do
    if [[ "$s" == "$target" ]]; then
      return 0
    fi
  done
  return 1
}

# Check TTY requirements honestly:
# Non-interactive without -y/MAC_BOOTSTRAP_YES fails early.
# Note: Even with -y, if sudo authentication is needed by Homebrew/casks, an interactive TTY may still be required.
if [[ "$ASSUME_YES" -eq 0 && (! -t 0 || ! -t 1 || ! -t 2) ]]; then
  echo "system-upgrade requires an interactive TTY; Homebrew may request sudo authentication" >&2
  exit 2
fi

export HOMEBREW_NO_UPGRADE_AUTO_UPDATES_CASKS="${HOMEBREW_NO_UPGRADE_AUTO_UPDATES_CASKS:-1}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BREW_BIN="${BREW_BIN:-$(command -v brew 2>/dev/null || echo '')}"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
SKILL_SOURCE="${SKILL_SOURCE:-}"

declare -A STAGE_STATUS
declare -A STAGE_REASON

record_result() {
  local stage="$1"
  local status="$2"
  local reason="${3:-}"
  STAGE_STATUS["$stage"]="$status"
  STAGE_REASON["$stage"]="$reason"
}

# Stage 1: packages (Homebrew update + reconcile + upgrade + zerobrew + cleanup)
run_packages() {
  echo "=== [packages] Updating Homebrew and reconciling packages from Brewfile... ==="
  if [[ -z "${BREW_BIN}" || ! -x "${BREW_BIN}" ]]; then
    echo "Error: Homebrew executable not found: '${BREW_BIN}'" >&2
    record_result "packages" "failed" "Homebrew executable not found"
    return 1
  fi

  if ! "${BREW_BIN}" update; then
    echo "Error: 'brew update' failed" >&2
    record_result "packages" "failed" "brew update failed"
    return 1
  fi

  if [[ -x "${ROOT_DIR}/scripts/brew-bundle.sh" ]]; then
    if ! "${ROOT_DIR}/scripts/brew-bundle.sh" install; then
      echo "Error: Package reconciliation failed (scripts/brew-bundle.sh install). Subsequent package upgrade steps skipped." >&2
      record_result "packages" "failed" "brew-bundle install reconciliation failed"
      return 1
    fi
  else
    echo "Warning: scripts/brew-bundle.sh not executable or not found" >&2
  fi

  if ! "${BREW_BIN}" upgrade; then
    echo "Error: 'brew upgrade' failed" >&2
    record_result "packages" "failed" "brew upgrade failed"
    return 1
  fi

  if command -v zb >/dev/null 2>&1; then
    export ZEROBREW_ROOT="${ZEROBREW_ROOT:-/opt/zerobrew}"
    export ZEROBREW_PREFIX="${ZEROBREW_PREFIX:-$ZEROBREW_ROOT}"
    if ! zb update || ! zb upgrade || ! zb gc; then
      echo "Error: Zerobrew update/upgrade/gc failed" >&2
      record_result "packages" "failed" "zerobrew operations failed"
      return 1
    fi
  fi

  if ! "${BREW_BIN}" cleanup; then
    echo "Error: 'brew cleanup' failed" >&2
    record_result "packages" "failed" "brew cleanup failed"
    return 1
  fi

  record_result "packages" "success"
  return 0
}

# Stage 2: bun (global Bun packages)
run_bun() {
  echo "=== [bun] Upgrading global Bun packages... ==="
  local BUN_BIN
  BUN_BIN="$(command -v bun 2>/dev/null || echo '')"
  if [[ -z "${BUN_BIN}" || ! -x "${BUN_BIN}" ]]; then
    echo "bun executable not found; skipping"
    record_result "bun" "skipped" "bun not installed"
    return 0
  fi

  if "${BUN_BIN}" update -g; then
    record_result "bun" "success"
    return 0
  else
    echo "Error: Bun global update failed" >&2
    record_result "bun" "failed" "bun update -g failed"
    return 1
  fi
}

# Stage 3: uv (managed tools)
run_uv() {
  echo "=== [uv] Upgrading uv managed tools... ==="
  local UV_BIN
  UV_BIN="$(command -v uv 2>/dev/null || echo '')"
  if [[ -z "${UV_BIN}" || ! -x "${UV_BIN}" ]]; then
    echo "uv executable not found; skipping"
    record_result "uv" "skipped" "uv not installed"
    return 0
  fi

  if "${UV_BIN}" tool upgrade --all; then
    record_result "uv" "success"
    return 0
  else
    echo "Error: uv tool upgrade failed" >&2
    record_result "uv" "failed" "uv tool upgrade failed"
    return 1
  fi
}

# Stage 4: claude (marketplace plugins)
run_claude() {
  echo "=== [claude] Updating Claude Code plugin marketplaces... ==="
  local CLAUDE_BIN
  CLAUDE_BIN="$(command -v claude 2>/dev/null || echo '')"
  if [[ -z "${CLAUDE_BIN}" || ! -x "${CLAUDE_BIN}" ]]; then
    echo "claude executable not found; skipping"
    record_result "claude" "skipped" "claude not installed"
    return 0
  fi

  if "${CLAUDE_BIN}" plugin marketplace update; then
    record_result "claude" "success"
    return 0
  else
    echo "Error: claude plugin marketplace update failed" >&2
    record_result "claude" "failed" "claude plugin marketplace update failed"
    return 1
  fi
}

# Stage 5: npm (manifest-managed global packages)
run_npm() {
  echo "=== [npm] Upgrading managed global npm packages... ==="
  if ! command -v npm >/dev/null 2>&1; then
    echo "Error: npm executable not found in PATH" >&2
    record_result "npm" "failed" "npm not installed"
    return 1
  fi

  local npm_script="${ROOT_DIR}/scripts/install-npm-global-packages.sh"
  if [[ ! -x "${npm_script}" ]]; then
    echo "Error: ${npm_script} not found or not executable" >&2
    record_result "npm" "failed" "install-npm-global-packages.sh not executable"
    return 1
  fi

  if (cd "${ROOT_DIR}" && "${npm_script}" --yes --upgrade); then
    record_result "npm" "success"
    return 0
  else
    echo "Error: npm global packages upgrade failed" >&2
    record_result "npm" "failed" "install-npm-global-packages.sh failed"
    return 1
  fi
}

# Stage 6: skills (global skills update + skill supply chain bundles and distribution)
run_skills() {
  echo "=== [skills] Updating global skills and supply chain bundles... ==="
  local stage_failed=0
  local failure_reason=""

  if command -v npx >/dev/null 2>&1; then
    echo "Updating global skills via npx..."
    if ! npx --yes skills update --global; then
      echo "Warning: npx skills update failed" >&2
      stage_failed=1
      failure_reason="npx skills update --global failed"
    fi
  else
    echo "npx not found; skipping npx global skills update"
  fi

  # Skill supply chain refresh
  if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Error: Python executable not found: ${PYTHON_BIN}" >&2
    record_result "skills" "failed" "Python executable not found for skill supply chain: ${PYTHON_BIN}"
    return 1
  fi

  echo "Refreshing approved external skill bundles..."
  local bundle_update_ok=1
  if [[ -n "${SKILL_SOURCE}" ]]; then
    if ! (cd "${ROOT_DIR}" && "${PYTHON_BIN}" scripts/skill_supply_chain.py update-bundles --source "${SKILL_SOURCE}"); then
      bundle_update_ok=0
    fi
  else
    if ! (cd "${ROOT_DIR}" && "${PYTHON_BIN}" scripts/skill_supply_chain.py update-bundles); then
      bundle_update_ok=0
    fi
  fi

  if [[ "$bundle_update_ok" -eq 0 ]]; then
    echo "Error: update-bundles failed. Distribute skipped due to bundle update failure." >&2
    stage_failed=1
    if [[ -z "$failure_reason" ]]; then
      failure_reason="update-bundles failed (distribute skipped)"
    else
      failure_reason="${failure_reason}; update-bundles failed (distribute skipped)"
    fi
  else
    echo "Distributing approved managed skills..."
    if ! (cd "${ROOT_DIR}" && "${PYTHON_BIN}" scripts/skill_supply_chain.py distribute); then
      echo "Error: skill distribute failed" >&2
      stage_failed=1
      if [[ -z "$failure_reason" ]]; then
        failure_reason="skill supply chain distribute failed"
      else
        failure_reason="${failure_reason}; skill supply chain distribute failed"
      fi
    fi
  fi

  if [[ "$stage_failed" -ne 0 ]]; then
    record_result "skills" "failed" "$failure_reason"
    return 1
  fi

  record_result "skills" "success"
  return 0
}

# Stage 7: chrome (patch Chrome Gemini features)
run_chrome() {
  echo "=== [chrome] Patching Chrome to ensure Gemini features remain enabled... ==="
  if (cd "${ROOT_DIR}" && make patch-chrome-gemini); then
    record_result "chrome" "success"
    return 0
  else
    echo "Error: make patch-chrome-gemini failed" >&2
    record_result "chrome" "failed" "make patch-chrome-gemini failed"
    return 1
  fi
}

# Execute requested stages
for stage in "${SELECTED_STAGES[@]}"; do
  case "$stage" in
    packages) run_packages || true ;;
    bun)      run_bun || true ;;
    uv)       run_uv || true ;;
    claude)   run_claude || true ;;
    npm)      run_npm || true ;;
    skills)   run_skills || true ;;
    chrome)   run_chrome || true ;;
  esac
done

# Output Stage Summary Table
echo ""
echo "=========================================="
echo "         System Upgrade Summary"
echo "=========================================="

OVERALL_SUCCESS=1
FAILED_STAGES=()

for stage in "${SELECTED_STAGES[@]}"; do
  status="${STAGE_STATUS[$stage]:-unknown}"
  reason="${STAGE_REASON[$stage]:-}"
  if [[ "$status" == "success" ]]; then
    printf "  %-12s [ SUCCESS ]\n" "$stage"
  elif [[ "$status" == "skipped" ]]; then
    if [[ -n "$reason" ]]; then
      printf "  %-12s [ SKIPPED ] (%s)\n" "$stage" "$reason"
    else
      printf "  %-12s [ SKIPPED ]\n" "$stage"
    fi
  else
    OVERALL_SUCCESS=0
    FAILED_STAGES+=("$stage")
    if [[ -n "$reason" ]]; then
      printf "  %-12s [ FAILED  ] (%s)\n" "$stage" "$reason"
    else
      printf "  %-12s [ FAILED  ]\n" "$stage"
    fi
  fi
done
echo "=========================================="

if [[ "$OVERALL_SUCCESS" -eq 1 ]]; then
  echo "All requested upgrade stages completed successfully."
  exit 0
else
  echo ""
  echo "System upgrade encountered failures in: ${FAILED_STAGES[*]}"
  FAILED_CSV="$(IFS=,; echo "${FAILED_STAGES[*]}")"
  echo "To retry only failed stages, run:"
  if [[ "$ASSUME_YES" -eq 1 ]]; then
    echo "  ./scripts/system-upgrade.sh --yes --only ${FAILED_CSV}"
    echo "  (or: make system-upgrade UPGRADE_ONLY=${FAILED_CSV})"
  else
    echo "  ./scripts/system-upgrade.sh --only ${FAILED_CSV}"
    echo "  (or: make system-upgrade UPGRADE_ONLY=${FAILED_CSV})"
  fi
  echo ""
  echo "Note: If failures were caused by authentication or sudo timeouts, run in an interactive terminal."
  exit 1
fi
