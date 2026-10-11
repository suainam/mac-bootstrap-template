#!/usr/bin/env bash
# brew-bundle.sh: Reconcile packages according to declared ownership.
# Usage:
#   scripts/brew-bundle.sh [install]      Normal reconcile / install
#   scripts/brew-bundle.sh migrate         Explicit ownership migration (transfers Brew packages to zb)
#   scripts/brew-bundle.sh --check         Check ownership alignment without making changes

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
    --check)
      MODE="check"
      ;;
    *)
      echo "Usage: $0 [install|migrate|--check]" >&2
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

# Keep manually installed GUI apps outside Homebrew ownership.
for entry in 'microsoft-edge:Microsoft Edge.app' 'zed:Zed.app' 'clash-verge-rev:Clash Verge.app'; do
  token="${entry%%:*}"
  app="${entry#*:}"
  if ! brew list --cask "$token" >/dev/null 2>&1 && { [ -d "/Applications/$app" ] || [ -d "$HOME/Applications/$app" ]; }; then
    export HOMEBREW_BUNDLE_CASK_SKIP="${HOMEBREW_BUNDLE_CASK_SKIP:-} $token"
  fi
done

# Ensure zb is available
if ! command -v zb >/dev/null 2>&1; then
  brew install zerobrewhq/zerobrew/zerobrew
fi

OWNERSHIP_SCRIPT="$DIR/scripts/package-ownership.sh"
if [ ! -x "$OWNERSHIP_SCRIPT" ]; then
  chmod +x "$OWNERSHIP_SCRIPT"
fi

# Load authoritative zerobrew formulas
ZB_DECLARED_MAP="$(mktemp)"
TMP_FORMULAS="$(mktemp)"
trap 'rm -f "$ZB_DECLARED_MAP" "$TMP_FORMULAS"' EXIT

"$OWNERSHIP_SCRIPT" list-zb > "$ZB_DECLARED_MAP"

# Get all declared formulas from active Brewfile (including profiles)
brew bundle list --file="$DIR/Brewfile" --formula > "$TMP_FORMULAS"

DESIRED_ZB=()
DESIRED_BREW=()
while IFS= read -r formula; do
  [ -n "$formula" ] || continue
  short_name="${formula##*/}"
  if /usr/bin/grep -Fxq "$short_name" "$ZB_DECLARED_MAP" || /usr/bin/grep -Fxq "$formula" "$ZB_DECLARED_MAP"; then
    case " ${HOMEBREW_BUNDLE_BREW_SKIP:-} " in
      *" $formula "*|*" $short_name "*) ;;
      *) DESIRED_ZB+=("$formula") ;;
    esac
  else
    case " ${HOMEBREW_BUNDLE_BREW_SKIP:-} " in
      *" $formula "*|*" $short_name "*) ;;
      *) DESIRED_BREW+=("$formula") ;;
    esac
  fi
done < "$TMP_FORMULAS"

# Detect currently installed packages in Homebrew
BREW_INSTALLED="$(brew list --formula)"

# Identify any zb-owned formula currently installed in Homebrew (mismatch)
MIGRATION_CANDIDATES=()
for formula in "${DESIRED_ZB[@]}"; do
  short_name="${formula##*/}"
  if printf '%s\n' "$BREW_INSTALLED" | /usr/bin/grep -Fxq "$short_name" || printf '%s\n' "$BREW_INSTALLED" | /usr/bin/grep -Fxq "$formula"; then
    MIGRATION_CANDIDATES+=("$formula")
  fi
done

if [ "$MODE" = "check" ]; then
  if [ "${#MIGRATION_CANDIDATES[@]}" -gt 0 ]; then
    echo "Ownership mismatch detected: the following packages are declared for Zerobrew but currently installed in Homebrew:" >&2
    printf '  - %s\n' "${MIGRATION_CANDIDATES[@]}" >&2
    echo "Run '$0 migrate' to transfer them safely." >&2
    exit 1
  fi
  echo "Package ownership is aligned."
  exit 0
fi

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

  # Install desired zb packages if any are missing in zb
  if [ "${#DESIRED_ZB[@]}" -gt 0 ]; then
    zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" init --no-modify-path
    zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" install "${DESIRED_ZB[@]}"
    zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" doctor

    # Ensure docker plugins are linked
    for formula in "${DESIRED_ZB[@]}"; do
      short_name="${formula##*/}"
      case "$short_name" in
        docker-buildx|docker-compose)
          mkdir -p "${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins"
          if [ -e "$ZEROBREW_PREFIX/lib/docker/cli-plugins/$short_name" ]; then
            ln -sfn "$ZEROBREW_PREFIX/lib/docker/cli-plugins/$short_name" "${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins/$short_name"
          fi
          ;;
      esac
    done
  fi

  # Tell brew bundle install to skip all zb formulas
  export HOMEBREW_BUNDLE_BREW_SKIP="${HOMEBREW_BUNDLE_BREW_SKIP:-} ${DESIRED_ZB[*]}"
  brew bundle install --no-upgrade --file="$DIR/Brewfile"
  exit 0
fi

# Explicit migrate mode
if [ "$MODE" = "migrate" ]; then
  echo "=== Running package ownership migration ==="
  if [ "${#MIGRATION_CANDIDATES[@]}" -eq 0 ]; then
    echo "No packages need migration from Homebrew to Zerobrew."
    # Ensure desired zb packages are installed
    if [ "${#DESIRED_ZB[@]}" -gt 0 ]; then
      zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" init --no-modify-path
      zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" install "${DESIRED_ZB[@]}"
      zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" doctor
    fi
    exit 0
  fi

  echo "Candidates for migration: ${MIGRATION_CANDIDATES[*]}"

  # 1. Global preflight of dependents for ALL candidates BEFORE any uninstall or mutation
  echo "--- Step 1: Preflighting Homebrew dependencies ---"
  PREFLIGHT_BLOCKED=0
  for formula in "${MIGRATION_CANDIDATES[@]}"; do
    short_name="${formula##*/}"
    dependents="$(brew uses --installed "$short_name" 2>/dev/null || brew uses --installed "$formula" 2>/dev/null || true)"
    # Filter out dependents that are themselves in MIGRATION_CANDIDATES
    real_dependents=()
    for dep in $dependents; do
      is_sibling=0
      for sibling in "${MIGRATION_CANDIDATES[@]}"; do
        if [ "$dep" = "$sibling" ] || [ "$dep" = "${sibling##*/}" ]; then
          is_sibling=1
          break
        fi
      done
      if [ "$is_sibling" -eq 0 ]; then
        real_dependents+=("$dep")
      fi
    done

    if [ "${#real_dependents[@]}" -gt 0 ]; then
      echo "Dependency blocker: $formula is required by installed Homebrew package(s): ${real_dependents[*]}" >&2
      PREFLIGHT_BLOCKED=1
    fi
  done

  if [ "$PREFLIGHT_BLOCKED" -ne 0 ]; then
    echo "Migration aborted: Dependency preflight failed. No changes were made." >&2
    echo "Resolve dependents or keep packages in Homebrew before retrying." >&2
    exit 1
  fi
  echo "Preflight passed. No external Homebrew dependents found."

  # 2. Install and initialize packages in Zerobrew
  echo "--- Step 2: Installing in Zerobrew ---"
  zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" init --no-modify-path
  zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" install "${MIGRATION_CANDIDATES[@]}"

  # 3. Verify installs and runtime health in Zerobrew
  echo "--- Step 3: Verifying Zerobrew health and binaries ---"
  zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" doctor

  for formula in "${MIGRATION_CANDIDATES[@]}"; do
    short_name="${formula##*/}"
    # Verify binary exists and is executable under ZEROBREW_PREFIX
    case "$short_name" in
      docker-buildx|docker-compose)
        plugin_src="$ZEROBREW_PREFIX/lib/docker/cli-plugins/$short_name"
        if [ ! -f "$plugin_src" ]; then
          echo "Verification error: $plugin_src not found after zb install" >&2
          exit 1
        fi
        mkdir -p "${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins"
        ln -sfn "$plugin_src" "${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins/$short_name"
        ;;
      *)
        if [ ! -x "$ZEROBREW_PREFIX/bin/$short_name" ] && [ ! -x "$ZEROBREW_PREFIX/sbin/$short_name" ]; then
          echo "Verification error: $short_name binary not found/executable in $ZEROBREW_PREFIX/bin or sbin" >&2
          exit 1
        fi
        ;;
    esac
  done
  echo "Verification succeeded."

  # 4. Safely remove old Homebrew copies (NEVER ignore dependencies)
  echo "--- Step 4: Removing old Homebrew copies ---"
  for formula in "${MIGRATION_CANDIDATES[@]}"; do
    short_name="${formula##*/}"
    echo "Uninstalling $formula from Homebrew..."
    brew uninstall "$short_name" || brew uninstall "$formula"
  done

  echo "=== Migration complete ==="
  echo "All migrated packages are now managed exclusively by Zerobrew."
fi
