#!/usr/bin/env bash
# herdr-dispatch.sh — Thin, deterministic entrypoint for dispatch skill
# Forwards execution and contract validation to dispatch.py

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_PY="${SCRIPT_DIR}/dispatch.py"

# Subcommands: state, lint
if [[ $# -gt 0 ]]; then
  case "$1" in
    state|lint)
      exec python3 "${ENGINE_PY}" "$@"
      ;;
  esac
fi

if [[ "${HERDR_ENV:-}" != "1" || -z "${HERDR_PANE_ID:-}" ]]; then
  echo "Error: Must be run inside an active Herdr pane." >&2
  exit 1
fi

ROLE="writer"
KIND=""
NAME=""
TASK=""
MODEL=""
REPO="${PWD}"
BRANCH=""
BASE=""
PRINT=false
AUTO=false
YOLO=false
DELEGATION_LEVEL="OUTCOME_ONLY"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      grep '^#' "$0" | cut -c 3-
      exit 0
      ;;
    --role) ROLE="$2"; shift 2 ;;
    --kind) KIND="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --task) TASK="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --cwd) REPO="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --base) BASE="$2"; shift 2 ;;
    --print) PRINT=true; ROLE="researcher"; shift ;;
    --delegation-level) DELEGATION_LEVEL="$2"; shift 2 ;;
    --auto) AUTO=true; shift ;;
    --yolo|--dangerously-skip-permissions) YOLO=true; shift ;;
    --push)
      echo "Error: --push is strictly prohibited. Deployment and pushing MUST go through Human Gate." >&2
      exit 2
      ;;
    --wait)
      echo "Notice: --wait is deprecated. Dispatch enforces non-blocking Fire-and-Yield." >&2
      shift
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${TASK}" ]]; then
  echo "Error: --task <file> is required." >&2
  exit 1
fi

# Pre-flight Gate: Enforce Qiaomu Goal Contract & Anti-Pseudo-Delegation via dispatch_engine.py
python3 "${ENGINE_PY}" lint "${TASK}" --delegation-level "${DELEGATION_LEVEL}"

# Auto-route agent kind based on Diamond role if not explicitly provided
if [[ -z "${KIND}" ]]; then
  case "${ROLE}" in
    researcher) KIND="opencode" ;;
    skeptic)    KIND="agy" ;;
    writer)     KIND="codex" ;;
    *)          KIND="opencode" ;;
  esac
fi

# Portable timeout execution helper
run_with_timeout() {
  local duration="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "${duration}" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "${duration}" "$@"
  elif command -v perl >/dev/null 2>&1; then
    perl -e 'alarm shift; exec @ARGV' "${duration}" "$@"
  else
    "$@"
  fi
}

# ── Diamond: Researcher (Zero-Worktree, Non-Interactive Print Mode) ────────────
if [[ "${ROLE}" == "researcher" ]]; then
  echo "==> [Diamond:Researcher] Running non-interactive read-only probe via ${KIND} (timeout 180s)..."
  TASK_TEXT="$(cat "${TASK}")"
  case "${KIND}" in
    opencode)
      if [[ -n "${MODEL}" ]]; then
        run_with_timeout 180 opencode run --auto -m "${MODEL}" "${TASK_TEXT}"
      else
        run_with_timeout 180 opencode run --auto "${TASK_TEXT}"
      fi
      ;;
    agy)
      AGY_BIN="$(command -v agy 2>/dev/null || echo "${HOME}/.local/bin/agy")"
      if [[ -n "${MODEL}" ]]; then
        run_with_timeout 180 "$AGY_BIN" -p "${TASK_TEXT}" --model "${MODEL}"
      else
        run_with_timeout 180 "$AGY_BIN" -p "${TASK_TEXT}"
      fi
      ;;
    *)
      run_with_timeout 180 opencode run --auto "${TASK_TEXT}"
      ;;
  esac
  exit 0
fi

# ── Diamond: Writer / Skeptic (Isolated Worktree Execution) ────────────────────
if [[ -z "${NAME}" ]]; then
  NAME="${ROLE}-$(uuidgen | tr '[:upper:]' '[:lower:]' | head -c 6)"
fi

if ! [[ "${NAME}" =~ ^[a-z][a-z0-9_-]{0,31}$ ]]; then
  echo "Error: Lane name '${NAME}' is invalid. Must match regex ^[a-z][a-z0-9_-]{0,31}$ (lowercase, no dots, length <= 32)." >&2
  exit 1
fi

if [[ -z "${BRANCH}" ]]; then
  BRANCH="feat/${NAME}"
fi

REPO_ROOT="$(git -C "${REPO}" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
  echo "Error: Target directory '${REPO}' is not a git repository." >&2
  exit 1
fi

echo "==> [Diamond:${ROLE}] Creating Herdr worktree for lane '${NAME}' (branch: ${BRANCH})..."
CREATE_ARGS=(--cwd "${REPO_ROOT}" --branch "${BRANCH}" --label "${NAME}" --no-focus)
if [[ -n "${BASE}" ]]; then
  CREATE_ARGS+=(--base "${BASE}")
fi
CREATE_JSON="$(herdr worktree create "${CREATE_ARGS[@]}")"

PANE_ID="$(jq -er '.result.root_pane.pane_id' <<<"${CREATE_JSON}")" || { echo "Error: Failed to parse root_pane.pane_id from herdr response." >&2; exit 1; }
CHECKOUT="$(jq -er '.result.worktree.path' <<<"${CREATE_JSON}")" || { echo "Error: Failed to parse worktree.path from herdr response." >&2; exit 1; }
WORKSPACE_ID="$(jq -er '.result.workspace.workspace_id' <<<"${CREATE_JSON}")" || { echo "Error: Failed to parse workspace_id from herdr response." >&2; exit 1; }

if [[ -z "${PANE_ID}" || "${PANE_ID}" == "null" || -z "${CHECKOUT}" || "${CHECKOUT}" == "null" ]]; then
  echo "Error: herdr worktree create returned null coordinates: pane=${PANE_ID}, checkout=${CHECKOUT}" >&2
  exit 1
fi

REPO_SLUG="$(basename "${REPO_ROOT}")"

# Enforce pane semantic renaming (Label is display-only; pane_id remains addressable)
herdr pane rename "${PANE_ID}" "${NAME}" >/dev/null 2>&1 || true

echo "==> Worktree ready: ${CHECKOUT} (pane: ${PANE_ID}, label: ${NAME}, workspace: ${WORKSPACE_ID})"

# Setup .dispatch directory & telemetry initialization
mkdir -p "${CHECKOUT}/.dispatch"
COMMON_GIT_DIR="$(git -C "${CHECKOUT}" rev-parse --path-format=absolute --git-common-dir)"
EXCLUDE_FILE="${COMMON_GIT_DIR}/info/exclude"
mkdir -p "$(dirname "${EXCLUDE_FILE}")"
grep -qxF '.dispatch/' "${EXCLUDE_FILE}" 2>/dev/null || echo '.dispatch/' >> "${EXCLUDE_FILE}"

START_EPOCH="$(date +%s)"
echo "${START_EPOCH}" > "${CHECKOUT}/.dispatch/START_EPOCH"
cat <<EOF > "${CHECKOUT}/.dispatch/META.json"
{
  "lane": "${NAME}",
  "role": "${ROLE}",
  "kind": "${KIND}",
  "branch": "${BRANCH}",
  "pane_id": "${PANE_ID}",
  "workspace_id": "${WORKSPACE_ID}",
  "repo_slug": "${REPO_SLUG}",
  "start_epoch": ${START_EPOCH}
}
EOF

NOTIFY_SIGNATURE="[${PANE_ID}_${KIND}_${REPO_SLUG}]"
HANDOFF_TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
HANDOFF_FILENAME="${REPO_SLUG}-${NAME}-handoff-${HANDOFF_TIMESTAMP}.md"
mkdir -p "${HOME}/Documents/handoffs"

HANDOFF_BLOCK="# Handoff protocol (mandatory)
Before sending the notify-back command, you MUST write a structured Handoff document:
  ${HOME}/Documents/handoffs/${HANDOFF_FILENAME}
Include:
1. Executive summary of what was accomplished.
2. Core conclusions and decisions made.
3. Verification proof (exact test commands, assertions passed, line numbers).
4. Residual risks and next steps.
Never include secrets, tokens, passwords or credentials - redact and desensitize!

# Notify-back (exact format)
Assert the Handoff file exists and is non-empty before notifying:
  test -s \"${HOME}/Documents/handoffs/${HANDOFF_FILENAME}\" && \\
  herdr agent prompt ${HERDR_PANE_ID} \"\n[NOTIFY] ${NOTIFY_SIGNATURE}\nDONE: <one-liner conclusion>\nHandoff: ~/Documents/handoffs/${HANDOFF_FILENAME}\""

cp "${TASK}" "${CHECKOUT}/.dispatch/TASK.md"
{
  echo ""
  echo "${HANDOFF_BLOCK}"
} >> "${CHECKOUT}/.dispatch/TASK.md"

cat <<EOF > "${CHECKOUT}/.dispatch/progress.md"
# Progress (${ROLE})
- [ ] Initialized
EOF

# Build model & permission arguments per agent kind (Dynamic & Least-Privilege)
AGENT_ARGS=()
case "${KIND}" in
  codex)
    if [[ -n "${MODEL}" ]]; then
      AGENT_ARGS+=("-m" "${MODEL}")
    fi
    ;;
  claude)
    if [[ -n "${MODEL}" ]]; then
      AGENT_ARGS+=("--model" "${MODEL}")
    fi
    if [[ "${AUTO}" == "true" || "${YOLO}" == "true" ]]; then
      AGENT_ARGS+=("--dangerously-skip-permissions")
    fi
    ;;
  agy)
    if [[ -n "${MODEL}" ]]; then
      AGENT_ARGS+=("--model" "${MODEL}")
    fi
    AGENT_ARGS+=("--log-file" "${CHECKOUT}/.dispatch/agy.log")
    if [[ "${AUTO}" == "true" || "${YOLO}" == "true" ]]; then
      AGENT_ARGS+=("--dangerously-skip-permissions")
    fi
    ;;
  opencode)
    # Bare opencode starts the interactive TUI and does not accept -m/--model.
    # Only pass --auto for non-blocking permission handling.
    if [[ "${AUTO}" == "true" ]]; then
      AGENT_ARGS+=("--auto")
    fi
    ;;
esac

echo "==> Step 1: Starting ${KIND} agent in pane ${PANE_ID}..."
EXTRA_FLAG=()
if [[ ${#AGENT_ARGS[@]} -gt 0 ]]; then
  EXTRA_FLAG+=(-- "${AGENT_ARGS[@]}")
fi

herdr agent start "${NAME}" --kind "${KIND}" --pane "${PANE_ID}" --timeout 60000 "${EXTRA_FLAG[@]}"

# Two-Step Protocol: loop probe readiness up to 15s to defeat cold-start modal races
echo "==> Step 1.5: Probing interactive readiness & resolving trust modals..."
for ((i=1; i<=15; i++)); do
  sleep 1
  VISIBLE="$(herdr pane read "${PANE_ID}" --source visible 2>/dev/null || true)"
  if echo "${VISIBLE}" | grep -qE "trust|Trust|Accessing workspace|trust this folder"; then
    echo "==> Resolving workspace trust modal..."
    herdr pane send-keys "${PANE_ID}" enter
    sleep 1
    break
  elif echo "${VISIBLE}" | grep -qE "Ask anything|Ask Codex|❯|> "; then
    break
  fi
done

echo "==> Step 2: Injecting prompt into ready composer..."
herdr agent prompt "${NAME}" "Read .dispatch/TASK.md in this directory and work through it step by step. Keep .dispatch/progress.md updated. Write .dispatch/DONE when finished and run the notify-back command."

echo "==> [Diamond:${ROLE}] Dispatch complete! Lane '${NAME}' is running in workspace ${WORKSPACE_ID}."
echo "    Signature: ${NOTIFY_SIGNATURE}"
echo "    Handoff:   ~/Documents/handoffs/${HANDOFF_FILENAME}"
echo "    Monitor:   herdr agent read ${NAME} --source visible"
echo "    Yielding:  Main orchestrator session remains interactive."
