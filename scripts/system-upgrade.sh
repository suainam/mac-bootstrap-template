#!/usr/bin/env bash
set -euo pipefail

ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
  esac
done
if [[ "${MAC_BOOTSTRAP_YES:-0}" -eq 1 ]]; then
  ASSUME_YES=1
fi

if [[ "$ASSUME_YES" -eq 0 && (! -t 0 || ! -t 1 || ! -t 2) ]]; then
  echo "system-upgrade requires an interactive TTY; Homebrew may request sudo authentication" >&2
  exit 2
fi
export HOMEBREW_NO_UPGRADE_AUTO_UPDATES_CASKS="${HOMEBREW_NO_UPGRADE_AUTO_UPDATES_CASKS:-1}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BREW_BIN="${BREW_BIN:-$(command -v brew 2>/dev/null || echo '')}"
TOPGRADE_BIN="${TOPGRADE_BIN:-$(command -v topgrade 2>/dev/null || echo '')}"
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

if [[ -n "${TOPGRADE_BIN}" && -x "${TOPGRADE_BIN}" ]]; then
  echo "Running Topgrade universal upgrade..."
  "${TOPGRADE_BIN}" --disable node
else
  echo "Running Homebrew update and upgrade in the current terminal..."
  "${BREW_BIN}" update
  "${BREW_BIN}" upgrade
fi
echo "Upgrading managed global npm packages..."
(
  cd "${ROOT_DIR}"
  ./scripts/install-npm-global-packages.sh --yes --upgrade
)
echo "Patching Chrome to ensure Gemini features remain enabled..."
(
  cd "${ROOT_DIR}"
  make patch-chrome-gemini || true
)

echo "Refreshing approved external skills: ${SKILL_SOURCE}"
(
  cd "${ROOT_DIR}"
  "${PYTHON_BIN}" scripts/skill_supply_chain.py update-bundles --source "${SKILL_SOURCE}"
  "${PYTHON_BIN}" scripts/skill_supply_chain.py distribute
)
