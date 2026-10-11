#!/usr/bin/env bash
# brew-bundle.sh: Reconcile packages according to declared ownership.
# Usage:
#   scripts/brew-bundle.sh [install]      Normal reconcile / install
#   scripts/brew-bundle.sh migrate         Explicit ownership migration (transfers Brew packages to zb)

set -euo pipefail

MODE="install"
if [ "$#" -gt 0 ]; then
  case "$1" in
    install)
      MODE="install"
      ;;
    migrate)
      MODE="migrate"
      ;;
    *)
      echo "Usage: $0 [install|migrate]" >&2
      exit 2
      ;;
  esac
fi

DIR="$(cd "$(dirname "$0")/.." && pwd)"
export MAC_BOOTSTRAP_PRIVATE_DIR="${MAC_BOOTSTRAP_PRIVATE_DIR:-$DIR/../private}"
export MAC_BOOTSTRAP_PROFILE="${MAC_BOOTSTRAP_PROFILE:-$("$DIR/scripts/resolve-profile.sh" 2>/dev/null || echo "work")}"

# Homebrew 7 filters env in Ruby runtime; export HOMEBREW_* variables for safe transport.
export HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR="$MAC_BOOTSTRAP_PRIVATE_DIR"
export HOMEBREW_MAC_BOOTSTRAP_PROFILE="$MAC_BOOTSTRAP_PROFILE"

export ZEROBREW_ROOT="${ZEROBREW_ROOT:-/opt/zerobrew}"
export ZEROBREW_PREFIX="${ZEROBREW_PREFIX:-$ZEROBREW_ROOT}"
if [ "${#ZEROBREW_PREFIX}" -gt 13 ]; then
  echo "ZEROBREW_PREFIX must be at most 13 characters on macOS: $ZEROBREW_PREFIX" >&2
  exit 2
fi
if [ ! -d "$ZEROBREW_ROOT" ] || [ ! -w "$ZEROBREW_ROOT" ]; then
  echo "Create a user-owned zerobrew directory before bootstrap:" >&2
  echo "sudo install -d -o \"\$(id -un)\" -g \"\$(id -gn)\" -m 755 \"$ZEROBREW_ROOT\"" >&2
  exit 2
fi

# Ensure jq is installed for ownership manifest queries
if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required to query package ownership" >&2
  exit 1
fi

# Load authoritative zerobrew formulas from package-ownership.sh
OWNERSHIP_SCRIPT="$DIR/scripts/package-ownership.sh"
if [ ! -x "$OWNERSHIP_SCRIPT" ]; then
  echo "Error: $OWNERSHIP_SCRIPT is not executable" >&2
  exit 1
fi

ZB_DECLARED_MAP="$(mktemp)"
TMP_FORMULAS="$(mktemp)"
trap 'rm -f "$ZB_DECLARED_MAP" "$TMP_FORMULAS"' EXIT

"$OWNERSHIP_SCRIPT" list-zb > "$ZB_DECLARED_MAP"

# Get all declared formulas from active Brewfile (including profiles)
brew bundle list --file="$DIR/Brewfile" --formula > "$TMP_FORMULAS"

normalize_formula() {
  local target="$1"
  case "$target" in
    homebrew/core/*) echo "${target#homebrew/core/}" ;;
    core/*) echo "${target#core/}" ;;
    *) echo "$target" ;;
  esac
}

DESIRED_ZB=()
while IFS= read -r formula; do
  [ -n "$formula" ] || continue
  normalized="$(normalize_formula "$formula")"
  if /usr/bin/grep -Fxq "$normalized" "$ZB_DECLARED_MAP"; then
    case " ${HOMEBREW_BUNDLE_BREW_SKIP:-} " in
      *" $formula "*|*" $normalized "*) ;;
      *) DESIRED_ZB+=("$formula") ;;
    esac
  fi
done < "$TMP_FORMULAS"

# Detect currently installed packages in Homebrew
BREW_INSTALLED="$(brew list --formula)"

# Identify any zb-owned formula currently installed in Homebrew (mismatch)
MIGRATION_CANDIDATES=()
for formula in "${DESIRED_ZB[@]}"; do
  normalized="$(normalize_formula "$formula")"
  if printf '%s\n' "$BREW_INSTALLED" | /usr/bin/grep -Fxq "$normalized" || printf '%s\n' "$BREW_INSTALLED" | /usr/bin/grep -Fxq "$formula"; then
    MIGRATION_CANDIDATES+=("$formula")
  fi
done

# Shared helper: ensure zb packages are installed, healthy, and docker plugins linked
reconcile_zb_packages() {
  local packages=("$@")
  [ "${#packages[@]}" -gt 0 ] || return 0

  if ! command -v zb >/dev/null 2>&1; then
    brew install zerobrewhq/zerobrew/zerobrew
  fi

  zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" init --no-modify-path
  zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" install "${packages[@]}"
  zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" doctor

  for formula in "${packages[@]}"; do
    normalized="$(normalize_formula "$formula")"
    case "$normalized" in
      docker-buildx|docker-compose)
        mkdir -p "${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins"
        local plugin_src="$ZEROBREW_PREFIX/lib/docker/cli-plugins/$normalized"
        if [ -e "$plugin_src" ]; then
          ln -sfn "$plugin_src" "${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins/$normalized"
        fi
        ;;
    esac
  done
}

# Normal install mode MUST NOT silently transfer or uninstall Brew packages
if [ "$MODE" = "install" ]; then
  if [ "${#MIGRATION_CANDIDATES[@]}" -gt 0 ]; then
    echo "Error: Ownership mismatch detected. The following formulas are declared for Zerobrew (zb) but are currently installed in Homebrew (brew):" >&2
    printf '  - %s\n' "${MIGRATION_CANDIDATES[@]}" >&2
    echo "" >&2
    echo "Normal install/reconcile will not silently transfer or uninstall existing Homebrew packages." >&2
    echo "To safely migrate these packages to Zerobrew, run:" >&2
    echo "  $0 migrate" >&2
    echo "Or run 'make package-migrate' if available." >&2
    exit 1
  fi

  # Keep manually installed GUI apps outside Homebrew ownership.
  for entry in 'microsoft-edge:Microsoft Edge.app' 'zed:Zed.app' 'clash-verge-rev:Clash Verge.app'; do
    token="${entry%%:*}"
    app="${entry#*:}"
    if ! brew list --cask "$token" >/dev/null 2>&1 && { [ -d "/Applications/$app" ] || [ -d "$HOME/Applications/$app" ]; }; then
      export HOMEBREW_BUNDLE_CASK_SKIP="${HOMEBREW_BUNDLE_CASK_SKIP:-} $token"
    fi
  done

  reconcile_zb_packages "${DESIRED_ZB[@]}"

  # Tell brew bundle install to skip all zb formulas
  export HOMEBREW_BUNDLE_BREW_SKIP="${HOMEBREW_BUNDLE_BREW_SKIP:-} ${DESIRED_ZB[*]}"
  brew bundle install --no-upgrade --file="$DIR/Brewfile"
  exit 0
fi

# Explicit migrate mode verification
verify_installed_tool() {
  local normalized="$1"
  case "$normalized" in
    docker-buildx|docker-compose)
      local plugin_src="$ZEROBREW_PREFIX/lib/docker/cli-plugins/$normalized"
      if [ ! -f "$plugin_src" ]; then
        echo "Verification error: plugin $plugin_src not found" >&2
        return 1
      fi
      mkdir -p "${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins"
      ln -sfn "$plugin_src" "${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins/$normalized"
      "$plugin_src" version >/dev/null 2>&1 || "$plugin_src" --version >/dev/null 2>&1 || true
      ;;
    ast-grep)
      local bin=""
      if [ -x "$ZEROBREW_PREFIX/bin/ast-grep" ]; then
        bin="$ZEROBREW_PREFIX/bin/ast-grep"
      elif [ -x "$ZEROBREW_PREFIX/bin/sg" ]; then
        bin="$ZEROBREW_PREFIX/bin/sg"
      else
        echo "Verification error: ast-grep (or sg) not found in $ZEROBREW_PREFIX/bin" >&2
        return 1
      fi
      "$bin" --version >/dev/null 2>&1 || return 1
      ;;
    tree-sitter-cli)
      local bin=""
      if [ -x "$ZEROBREW_PREFIX/bin/tree-sitter-cli" ]; then
        bin="$ZEROBREW_PREFIX/bin/tree-sitter-cli"
      elif [ -x "$ZEROBREW_PREFIX/bin/tree-sitter" ]; then
        bin="$ZEROBREW_PREFIX/bin/tree-sitter"
      else
        echo "Verification error: tree-sitter-cli (or tree-sitter) not found in $ZEROBREW_PREFIX/bin" >&2
        return 1
      fi
      "$bin" --version >/dev/null 2>&1 || return 1
      ;;
    pngpaste)
      local bin="$ZEROBREW_PREFIX/bin/pngpaste"
      if [ ! -x "$bin" ]; then
        echo "Verification error: $bin not found or not executable" >&2
        return 1
      fi
      ;;
    *)
      local bin="$ZEROBREW_PREFIX/bin/$normalized"
      [ -x "$bin" ] || bin="$ZEROBREW_PREFIX/sbin/$normalized"
      if [ ! -x "$bin" ]; then
        echo "Verification error: binary for $normalized not found in $ZEROBREW_PREFIX/bin or sbin" >&2
        return 1
      fi
      "$bin" --version >/dev/null 2>&1 || true
      ;;
  esac
  return 0
}

if [ "$MODE" = "migrate" ]; then
  echo "=== Running package ownership migration ==="
  if [ "${#MIGRATION_CANDIDATES[@]}" -eq 0 ]; then
    echo "No packages need migration from Homebrew to Zerobrew."
    reconcile_zb_packages "${DESIRED_ZB[@]}"
    exit 0
  fi

  echo "Candidates for migration: ${MIGRATION_CANDIDATES[*]}"

  # 1. Global preflight of dependents for ALL candidates BEFORE any uninstall or mutation
  echo "--- Step 1: Preflighting Homebrew dependencies ---"
  PREFLIGHT_BLOCKED=0
  for formula in "${MIGRATION_CANDIDATES[@]}"; do
    normalized="$(normalize_formula "$formula")"
    if ! dependents="$(brew uses --installed "$normalized" 2>/dev/null)"; then
      if ! dependents="$(brew uses --installed "$formula")"; then
        echo "Error: Failed to query installed dependents for $formula from Homebrew" >&2
        exit 1
      fi
    fi

    if [ -n "$dependents" ]; then
      echo "Dependency blocker: $formula is required by installed Homebrew package(s): $dependents" >&2
      PREFLIGHT_BLOCKED=1
    fi
  done

  if [ "$PREFLIGHT_BLOCKED" -ne 0 ]; then
    echo "Migration aborted: Dependency preflight failed. No changes were made." >&2
    echo "Resolve dependents or keep packages in Homebrew before retrying." >&2
    exit 1
  fi
  echo "Preflight passed. No Homebrew dependents found."

  # 2. Install and initialize packages in Zerobrew
  echo "--- Step 2: Installing in Zerobrew ---"
  reconcile_zb_packages "${MIGRATION_CANDIDATES[@]}"

  # 3. Verify installs and runtime health in Zerobrew
  echo "--- Step 3: Verifying Zerobrew health and binaries ---"
  for formula in "${MIGRATION_CANDIDATES[@]}"; do
    normalized="$(normalize_formula "$formula")"
    if ! verify_installed_tool "$normalized"; then
      echo "Verification failed for $normalized; aborting before any Homebrew uninstallation" >&2
      exit 1
    fi
  done
  echo "Verification succeeded."

  # 4. Safely remove old Homebrew copies (NEVER ignore dependencies)
  echo "--- Step 4: Removing old Homebrew copies ---"
  for formula in "${MIGRATION_CANDIDATES[@]}"; do
    normalized="$(normalize_formula "$formula")"
    echo "Uninstalling $formula from Homebrew..."
    brew uninstall "$normalized" 2>/dev/null || brew uninstall "$formula"
  done

  echo "=== Migration complete ==="
  echo "All migrated packages are now managed exclusively by Zerobrew."
fi
