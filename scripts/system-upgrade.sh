#!/usr/bin/env bash
set -euo pipefail

if [[ ! -t 0 || ! -t 1 || ! -t 2 ]]; then
  echo "system-upgrade requires an interactive TTY; Homebrew may request sudo authentication" >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BREW_BIN="${BREW_BIN:-$(command -v brew || true)}"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
SKILL_SOURCE="${SKILL_SOURCE:-mattpocock-skills}"

if [[ -z "${BREW_BIN}" || ! -x "${BREW_BIN}" ]]; then
  echo "Homebrew executable not found" >&2
  exit 1
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python executable not found: ${PYTHON_BIN}" >&2
  exit 1
fi

echo "Running Homebrew update and upgrade in the current terminal..."
"${BREW_BIN}" update
"${BREW_BIN}" upgrade

echo "Refreshing approved external skills: ${SKILL_SOURCE}"
(
  cd "${ROOT_DIR}"
  "${PYTHON_BIN}" scripts/skill_supply_chain.py update-bundles --source "${SKILL_SOURCE}"
  "${PYTHON_BIN}" scripts/skill_supply_chain.py distribute
)
