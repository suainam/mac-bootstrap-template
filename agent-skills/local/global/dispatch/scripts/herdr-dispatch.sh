#!/usr/bin/env bash
# herdr-dispatch.sh — Unified, Diamond-integrated agent dispatch CLI
# Usage:
#   herdr-dispatch.sh --task <task-description-or-file> \
#                     [--role <researcher|writer|skeptic>] \
#                     [--kind <codex|opencode|claude|agy|omp>] \
#                     [--model <model-name>] \
#                     [--name <lane-name>] \
#                     [--cwd <repo-path>] \
#                     [--branch <branch-name>] \
#                     [--auto] \
#                     [--yolo]

set -euo pipefail

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
AUTO=false
YOLO=false

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
    --auto) AUTO=true; shift ;;
    --yolo|--dangerously-skip-permissions) YOLO=true; shift ;;
    --wait)
      echo "Notice: --wait is deprecated. Dispatch enforces non-blocking Fire-and-Yield." >&2
      shift
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${TASK}" ]]; then
  echo "Error: --task <description-or-file> is required." >&2
  exit 1
fi

# Auto-route agent kind based on Diamond role if not explicitly provided
if [[ -z "${KIND}" ]]; then
  case "${ROLE}" in
    researcher) KIND="opencode" ;;
    skeptic)    KIND="agy" ;;
    writer)     KIND="codex" ;;
    *)          KIND="opencode" ;;
  esac
fi

# ── Diamond: Researcher (Zero-Worktree, Non-Interactive Print Mode) ────────────
if [[ "${ROLE}" == "researcher" ]]; then
  echo "==> [Diamond:Researcher] Running non-interactive read-only probe via ${KIND} (timeout 180s)..."
  TASK_TEXT="${TASK}"
  if [[ -f "${TASK}" ]]; then
    TASK_TEXT="$(cat "${TASK}")"
  fi
  case "${KIND}" in
    opencode)
      if [[ -n "${MODEL}" ]]; then
        timeout 180 opencode run --auto -m "${MODEL}" "${TASK_TEXT}"
      else
        timeout 180 opencode run --auto "${TASK_TEXT}"
      fi
      ;;
    agy)
      AGY_BIN="$(command -v agy 2>/dev/null || echo "${HOME}/.local/bin/agy")"
      if [[ -n "${MODEL}" ]]; then
        timeout 180 "$AGY_BIN" -p "${TASK_TEXT}" --model "${MODEL}"
      else
        timeout 180 "$AGY_BIN" -p "${TASK_TEXT}"
      fi
      ;;
    *)
      timeout 180 opencode run --auto "${TASK_TEXT}"
      ;;
  esac
  exit 0
fi

# ── Diamond: Writer / Skeptic (Isolated Worktree Execution) ────────────────────
if [[ -z "${NAME}" ]]; then
  # UUID tail to guarantee zero collision in parallel lanes
  NAME="${ROLE}-$(uuidgen | tr '[:upper:]' '[:lower:]' | head -c 6)"
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
CREATE_JSON="$(herdr worktree create --cwd "${REPO_ROOT}" --branch "${BRANCH}" --label "${NAME}" --no-focus)"

PANE_ID="$(echo "${CREATE_JSON}" | jq -r '.result.root_pane.pane_id')"
CHECKOUT="$(echo "${CREATE_JSON}" | jq -r '.result.worktree.path')"
WORKSPACE_ID="$(echo "${CREATE_JSON}" | jq -r '.result.workspace.workspace_id')"
REPO_SLUG="$(basename "${REPO_ROOT}")"

echo "==> Worktree ready: ${CHECKOUT} (pane: ${PANE_ID}, workspace: ${WORKSPACE_ID})"

# Setup .dispatch directory & telemetry initialization
mkdir -p "${CHECKOUT}/.dispatch"
EXCLUDE_FILE="$(git -C "${CHECKOUT}" rev-parse --git-path info/exclude)"
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

if [[ -f "${TASK}" ]]; then
  # Lint Qiaomu Goal Contract (Mandatory Pre-flight Gate)
  MISSING=()
  grep -qiE '目标|outcome' "${TASK}" || MISSING+=("目标(Outcome)")
  grep -qiE '验证|verification' "${TASK}" || MISSING+=("验证(Verification)")
  grep -qiE '约束|constraints' "${TASK}" || MISSING+=("约束(Constraints)")
  grep -qiE '边界|boundaries' "${TASK}" || MISSING+=("边界(Boundaries)")
  grep -qiE '迭代策略|iteration policy' "${TASK}" || MISSING+=("迭代策略(Iteration Policy)")
  grep -qiE '完成条件|stop when' "${TASK}" || MISSING+=("完成条件(Stop when)")
  grep -qiE '暂停条件|pause if' "${TASK}" || MISSING+=("暂停条件(Pause if)")
  if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo "Error: Task file '${TASK}' violates Qiaomu Goal Contract." >&2
    echo "Missing mandatory sections: ${MISSING[*]}" >&2
    echo "Action required: Use /skill:qiaomu-goal-meta-skill to formulate a valid task before dispatch." >&2
    exit 1
  fi
  cp "${TASK}" "${CHECKOUT}/.dispatch/TASK.md"
  {
    echo ""
    echo "${HANDOFF_BLOCK}"
  } >> "${CHECKOUT}/.dispatch/TASK.md"
else
  cat <<EOF > "${CHECKOUT}/.dispatch/TASK.md"
# 目标 (Outcome - ${ROLE})
${TASK}

# 验证 (Verification)
运行项目提供的最小相关检查、测试或状态核验，获取运行时真实证据，并在 .dispatch/progress.md 与 Handoff 中保留输出/证据。

# 约束与脱敏 (Constraints & Security)
- 严禁在控制台输出、progress.md 或生成报告中打印或暴露任何密钥、Token、密码、凭据或隐私信息！必须脱敏！
- 调用 gh / git 远端交互若遇超时，防御性使用 env -u http_proxy -u https_proxy -u all_proxy 规避失效代理。
- 不修改与当前任务无关的文件，除非明确要求。

# 写入边界 (Boundaries)
只修改当前隔离 worktree 内与任务直接相关的文件；低权限临时目录（/tmp/ 与 .dispatch/）的读写全自动批准。

# 迭代策略 (Iteration Policy)
一次实现一个聚焦步骤，每次有意义改动后重跑检查；重试前先读日志，同工具连续失败 3 次需在 progress.md 记录 NEED_HELP 并暂停请示。

# 完成条件 (Stop when)
所有目标与验收标准达成且有验证证据支持，写出 .dispatch/DONE 与 Handoff 文件。

# 暂停条件 (Pause if)
需要远端 git push、生产变更、删除数据库/敏感资产、未知账密或发现所有权/方案存在重大歧义时暂停并请示人类。

# 进度更新 (Progress Protocol)
Keep .dispatch/progress.md updated after every major step.
When all items are finished and verified, write .dispatch/DONE with a concise summary.

${HANDOFF_BLOCK}
EOF
fi

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
    if [[ -n "${MODEL}" ]]; then
      AGENT_ARGS+=("-m" "${MODEL}")
    fi
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
