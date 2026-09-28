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
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
SKILL_SOURCE="${SKILL_SOURCE:-}"

if [[ -z "${BREW_BIN}" || ! -x "${BREW_BIN}" ]]; then
  echo "Homebrew executable not found" >&2
  exit 1
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python executable not found: ${PYTHON_BIN}" >&2
  exit 1
fi

echo "Updating Homebrew and reconciling packages from Brewfile..."
"${BREW_BIN}" update
if [[ -x "${ROOT_DIR}/scripts/brew-bundle.sh" ]]; then
  "${ROOT_DIR}/scripts/brew-bundle.sh" || {
    echo "Warning: brew-bundle encountered warnings or skipped items (some casks may require interactive sudo or DMG)" >&2
  }
fi
"${BREW_BIN}" upgrade
"${BREW_BIN}" cleanup

BUN_BIN="$(command -v bun 2>/dev/null || echo '')"
if [[ -n "${BUN_BIN}" && -x "${BUN_BIN}" ]]; then
  echo "Upgrading global Bun packages..."
  "${BUN_BIN}" update -g 2>/dev/null || true
fi

UV_BIN="$(command -v uv 2>/dev/null || echo '')"
if [[ -n "${UV_BIN}" && -x "${UV_BIN}" ]]; then
  echo "Upgrading uv managed tools..."
  "${UV_BIN}" tool upgrade --all 2>/dev/null || true
fi

CLAUDE_BIN="$(command -v claude 2>/dev/null || echo '')"
if [[ -n "${CLAUDE_BIN}" && -x "${CLAUDE_BIN}" ]]; then
  echo "Updating Claude Code plugin marketplaces..."
  "${CLAUDE_BIN}" plugin marketplace update 2>/dev/null || true
fi
echo "Upgrading managed global npm packages..."
(
  cd "${ROOT_DIR}"
  ./scripts/install-npm-global-packages.sh --yes --upgrade
)
echo "Updating global skills..."
if command -v npx >/dev/null 2>&1; then
  npx --yes skills update --global 2>/dev/null || true
fi
echo "Patching Chrome to ensure Gemini features remain enabled..."
(
  cd "${ROOT_DIR}"
  make patch-chrome-gemini || true
)
if [[ -f "${ROOT_DIR}/../Makefile" ]] && grep -q "mihomo-daemon-sync" "${ROOT_DIR}/../Makefile" 2>/dev/null; then
  echo "Synchronizing Mihomo daemon subscription and rules..."
  (
    cd "${ROOT_DIR}/.."
    make mihomo-daemon-sync || true
  )
fi


echo "Refreshing approved external skill bundles..."
(
  cd "${ROOT_DIR}"
  if [[ -n "${SKILL_SOURCE}" ]]; then
    "${PYTHON_BIN}" scripts/skill_supply_chain.py update-bundles --source "${SKILL_SOURCE}"
  else
    "${PYTHON_BIN}" scripts/skill_supply_chain.py update-bundles
  fi
  "${PYTHON_BIN}" scripts/skill_supply_chain.py distribute
)
