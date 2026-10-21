#!/usr/bin/env bash
# migrate-to-homebrew.sh — Migrate installed packages and runtime references
# from Zerobrew (zb) back to standard Homebrew.
#
# Safe, idempotent cutover:
# 1. Computes migration candidates from local zb inventory and active profile Brewfile.
# 2. Installs missing formulae into Homebrew.
# 3. Verifies each replacement via absolute Homebrew path before uninstalling from zb.
# 4. Relinks Docker CLI plugins to Homebrew.
# 5. Updates affected LaunchAgents (rclone-webdav, rustic) to Homebrew paths and reloads.
# 6. Cleans shell PATH exports.
# 7. Uninstalls verified formulae from Zerobrew (without deleting unknown state).
#
# Interruption or partial failure leaves working tools intact; rerun to continue.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

HOMEBREW_PREFIX="${HOMEBREW_PREFIX:-$(command -v brew >/dev/null 2>&1 && brew --prefix 2>/dev/null || echo '/opt/homebrew')}"
# An empty prefix silently rewrites LaunchAgents to /bin/<tool>, which does not exist.
if [ -z "$HOMEBREW_PREFIX" ]; then
  echo "Error: cannot resolve Homebrew prefix." >&2
  exit 2
fi
ZEROBREW_ROOT="${ZEROBREW_ROOT:-/opt/zerobrew}"
ZEROBREW_PREFIX="${ZEROBREW_PREFIX:-$ZEROBREW_ROOT}"
ZB_BIN="${ZB_BIN:-$(command -v zb 2>/dev/null || echo "$HOMEBREW_PREFIX/bin/zb")}"
DOCKER_PLUGINS_DIR="${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins"

echo "=== Homebrew Cutover Migration ==="
echo "Homebrew prefix: $HOMEBREW_PREFIX"
echo "Zerobrew root:   $ZEROBREW_ROOT"

# --- Step 1: Discover migration candidates ----------------------------------
echo "--- Step 1: Discovering installed Zerobrew kegs and active profile formulas ---"

normalize_formula() {
  local target="$1"
  case "$target" in
    homebrew/core/*) echo "${target#homebrew/core/}" ;;
    core/*) echo "${target#core/}" ;;
    *) echo "$target" ;;
  esac
}

INSTALLED_ZB=()
if [ -x "$ZB_BIN" ]; then
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    # zb prints this sentinel (not a formula) when nothing is installed.
    case "$line" in "No formulas installed."*) continue ;; esac
    name="$(echo "$line" | awk '{print $1}')"
    [ -n "$name" ] && INSTALLED_ZB+=("$name")
  done < <("$ZB_BIN" --root "$ZEROBREW_ROOT" list 2>/dev/null || true)
fi

# The zb database is authoritative. `Cellar/` can keep directories for kegs the
# database already dropped; scanning it then would resurrect removed packages.
ZB_DB="$ZEROBREW_ROOT/db/zb.sqlite3"
if [ "${#INSTALLED_ZB[@]}" -eq 0 ] && [ -f "$ZB_DB" ] && command -v sqlite3 >/dev/null 2>&1; then
  while IFS= read -r name; do
    [ -n "$name" ] && INSTALLED_ZB+=("$name")
  done < <(sqlite3 "$ZB_DB" "SELECT name FROM installed_kegs;" 2>/dev/null || true)
elif [ "${#INSTALLED_ZB[@]}" -eq 0 ] && [ ! -f "$ZB_DB" ] && [ -d "$ZEROBREW_ROOT/Cellar" ]; then
  # Legacy layouts without a database still need a filesystem fallback.
  for d in "$ZEROBREW_ROOT/Cellar"/*; do
    if [ -d "$d" ]; then
      INSTALLED_ZB+=("$(basename "$d")")
    fi
  done
fi

echo "Installed Zerobrew kegs (${#INSTALLED_ZB[@]}): ${INSTALLED_ZB[*]:-(none)}"

# Collect declared formulas for active profile
DECLARED_FORMULAS=()
if [ -f "$TEMPLATE_ROOT/Brewfile" ] && command -v brew >/dev/null 2>&1; then
  while IFS= read -r formula; do
    [ -n "$formula" ] || continue
    DECLARED_FORMULAS+=("$(normalize_formula "$formula")")
  done < <(brew bundle list --file="$TEMPLATE_ROOT/Brewfile" --formula 2>/dev/null || true)
fi

# Detect currently installed Homebrew formulas
BREW_INSTALLED="$(command -v brew >/dev/null 2>&1 && brew list --formula 2>/dev/null || true)"

# Union candidates: all zb-installed kegs + declared active formulas
ALL_CANDIDATES=()
for item in "${INSTALLED_ZB[@]}" "${DECLARED_FORMULAS[@]}"; do
  [ -n "$item" ] || continue
  norm="$(normalize_formula "$item")"
  # Deduplicate
  already=0
  for c in "${ALL_CANDIDATES[@]}"; do
    if [ "$c" = "$norm" ]; then
      already=1
      break
    fi
  done
  [ "$already" -eq 0 ] && ALL_CANDIDATES+=("$norm")
done

# Filter to candidates that actually need installation in Homebrew
NEED_INSTALL=()
for formula in "${ALL_CANDIDATES[@]}"; do
  [ "$formula" = "zerobrew" ] && continue
  if ! printf '%s\n' "$BREW_INSTALLED" | /usr/bin/grep -Fxq "$formula"; then
    NEED_INSTALL+=("$formula")
  fi
done

echo "Formulae needing Homebrew installation (${#NEED_INSTALL[@]}): ${NEED_INSTALL[*]:-(none)}"

# --- Step 2: Install missing formulae into Homebrew ------------------------
if [ "${#NEED_INSTALL[@]}" -gt 0 ]; then
  echo "--- Step 2: Installing missing formulae into Homebrew ---"
  export HOMEBREW_NO_AUTO_UPDATE="${HOMEBREW_NO_AUTO_UPDATE:-1}"
  # Try batch install first for speed, fall back to individual if batch fails
  if ! brew install "${NEED_INSTALL[@]}"; then
    echo "Warning: Batch brew install returned non-zero. Attempting individual installs..." >&2
    for formula in "${NEED_INSTALL[@]}"; do
      if ! brew list --formula 2>/dev/null | /usr/bin/grep -Fxq "$formula"; then
        brew install "$formula" || echo "Warning: Failed to install $formula in Homebrew" >&2
      fi
    done
  fi
  # Refresh brew installed list
  BREW_INSTALLED="$(brew list --formula 2>/dev/null || true)"
fi

# --- Step 3: Verify replacements via Homebrew paths -------------------------
echo "--- Step 3: Verifying tools via absolute Homebrew paths ---"

verify_homebrew_tool() {
  local tool="$1"
  local bin="$HOMEBREW_PREFIX/bin/$tool"
  [ -x "$bin" ] || bin="$HOMEBREW_PREFIX/sbin/$tool"

  case "$tool" in
    pngpaste)
      if [ -x "$bin" ]; then
        "$bin" -v >/dev/null 2>&1
        return $?
      fi
      ;;
    rclone)
      if [ -x "$bin" ]; then
        "$bin" version >/dev/null 2>&1
        return $?
      fi
      ;;
    rustic)
      if [ -x "$bin" ]; then
        "$bin" version >/dev/null 2>&1
        return $?
      fi
      ;;
    docker-compose)
      if [ -x "$bin" ]; then
        "$bin" --version >/dev/null 2>&1
        return $?
      elif [ -x "$HOMEBREW_PREFIX/lib/docker/cli-plugins/docker-compose" ]; then
        "$HOMEBREW_PREFIX/lib/docker/cli-plugins/docker-compose" --version >/dev/null 2>&1
        return $?
      fi
      ;;
    docker-buildx)
      if [ -x "$bin" ]; then
        "$bin" version >/dev/null 2>&1
        return $?
      elif [ -x "$HOMEBREW_PREFIX/lib/docker/cli-plugins/docker-buildx" ]; then
        "$HOMEBREW_PREFIX/lib/docker/cli-plugins/docker-buildx" version >/dev/null 2>&1
        return $?
      fi
      ;;
    ast-grep)
      if [ -x "$bin" ]; then
        "$bin" --version >/dev/null 2>&1
        return $?
      fi
      ;;
    tree-sitter-cli)
      local ts="$HOMEBREW_PREFIX/bin/tree-sitter"
      [ -x "$ts" ] || ts="$HOMEBREW_PREFIX/bin/tree-sitter-cli"
      if [ -x "$ts" ]; then
        "$ts" --version >/dev/null 2>&1
        return $?
      fi
      ;;
    *)
      if [ -x "$bin" ]; then
        if "$bin" --version >/dev/null 2>&1 || "$bin" -v >/dev/null 2>&1 || "$bin" -V >/dev/null 2>&1 || "$bin" -h >/dev/null 2>&1 || "$bin" --help >/dev/null 2>&1; then
          return 0
        fi
      fi
      ;;
  esac
  return 1
}

VERIFIED_TOOLS=()
FAILED_VERIFICATION=()

for formula in "${INSTALLED_ZB[@]}"; do
  [ "$formula" = "zerobrew" ] && continue
  if verify_homebrew_tool "$formula"; then
    VERIFIED_TOOLS+=("$formula")
  else
    FAILED_VERIFICATION+=("$formula")
  fi
done

echo "Verified Homebrew replacements (${#VERIFIED_TOOLS[@]}): ${VERIFIED_TOOLS[*]:-(none)}"
if [ "${#FAILED_VERIFICATION[@]}" -gt 0 ]; then
  echo "Verification failed for (${#FAILED_VERIFICATION[@]}): ${FAILED_VERIFICATION[*]}" >&2
  echo "These tools will NOT be removed from Zerobrew to preserve availability." >&2
fi
# A rerun finds already-migrated tools absent from the Zerobrew inventory, so
# membership in VERIFIED_TOOLS alone would block relinking. Verify directly too.
is_verified_tool() {
  local candidate="$1" item
  for item in "${VERIFIED_TOOLS[@]}"; do
    [ "$item" = "$candidate" ] && return 0
  done
  verify_homebrew_tool "$candidate"
}

# --- Step 4: Relink Docker CLI plugins --------------------------------------
echo "--- Step 4: Relinking Docker CLI plugins to Homebrew ---"
mkdir -p "$DOCKER_PLUGINS_DIR"

relink_docker_plugin() {
  local plugin="$1"
  local target=""
  if [ -e "$HOMEBREW_PREFIX/lib/docker/cli-plugins/$plugin" ]; then
    target="$HOMEBREW_PREFIX/lib/docker/cli-plugins/$plugin"
  elif [ -e "$HOMEBREW_PREFIX/bin/$plugin" ]; then
    target="$HOMEBREW_PREFIX/bin/$plugin"
  fi

  if [ -z "$target" ]; then
    return 0
  fi
  if ! is_verified_tool "$plugin"; then
    echo "  Keeping $plugin plugin link: Homebrew replacement is unverified" >&2
    return 0
  fi
  ln -sfn "$target" "$DOCKER_PLUGINS_DIR/$plugin"
  echo "  Relinked $plugin -> $target"
}

relink_docker_plugin "docker-compose"
relink_docker_plugin "docker-buildx"

# --- Step 5: Update affected LaunchAgents -----------------------------------
echo "--- Step 5: Repointing LaunchAgents to Homebrew ---"

RCLONE_PLIST="$HOME/Library/LaunchAgents/com.auroraops.rclone-webdav.plist"
if is_verified_tool rclone && [ -f "$RCLONE_PLIST" ] && /usr/bin/grep -q '/opt/zerobrew/bin/rclone' "$RCLONE_PLIST"; then
  echo "  Updating com.auroraops.rclone-webdav.plist..."
  if command -v launchctl >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)/com.auroraops.rclone-webdav" 2>/dev/null || true
  fi
  sed -i '' "s|/opt/zerobrew/bin/rclone|$HOMEBREW_PREFIX/bin/rclone|g" "$RCLONE_PLIST"
  if command -v launchctl >/dev/null 2>&1; then
    launchctl bootstrap "gui/$(id -u)" "$RCLONE_PLIST" 2>/dev/null || true
    echo "  Reloaded com.auroraops.rclone-webdav"
  fi
fi

if is_verified_tool rustic; then
  for rustic_plist in "$HOME/Library/LaunchAgents"/com.auroraops.rustic-*.plist; do
    [ -f "$rustic_plist" ] || continue
    if /usr/bin/grep -q '/opt/zerobrew' "$rustic_plist"; then
      echo "  Updating $(basename "$rustic_plist")..."
      label="$(basename "$rustic_plist" .plist)"
      if command -v launchctl >/dev/null 2>&1; then
        launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
      fi
      sed -i '' "s|/opt/zerobrew/bin/rustic|$HOMEBREW_PREFIX/bin/rustic|g" "$rustic_plist"
      sed -i '' "s|/opt/zerobrew/bin:/opt/zerobrew/sbin:||g" "$rustic_plist"
      sed -i '' "s|:/opt/zerobrew/bin:/opt/zerobrew/sbin||g" "$rustic_plist"
      if command -v launchctl >/dev/null 2>&1; then
        launchctl bootstrap "gui/$(id -u)" "$rustic_plist" 2>/dev/null || true
      fi
    fi
  done
fi

# --- Step 6: Uninstall verified packages from Zerobrew ----------------------
echo "--- Step 6: Removing verified formulae from Zerobrew ---"

FAILED_UNINSTALL=()
if [ -x "$ZB_BIN" ] && [ "${#VERIFIED_TOOLS[@]}" -gt 0 ]; then
  for formula in "${VERIFIED_TOOLS[@]}"; do
    echo "  Removing $formula from Zerobrew..."
    if ! { "$ZB_BIN" --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" uninstall "$formula" 2>/dev/null || \
      "$ZB_BIN" --root "$ZEROBREW_ROOT" uninstall "$formula" 2>/dev/null; }; then
      FAILED_UNINSTALL+=("$formula")
      echo "Warning: failed to uninstall $formula from Zerobrew" >&2
    fi
  done
fi

if [ "${#FAILED_UNINSTALL[@]}" -gt 0 ]; then
  echo "Note: ${#FAILED_UNINSTALL[@]} tool(s) remain installed in Zerobrew after failed uninstall." >&2
fi
if [ "${#FAILED_VERIFICATION[@]}" -gt 0 ] || [ "${#FAILED_UNINSTALL[@]}" -gt 0 ]; then
  if [ "${#FAILED_VERIFICATION[@]}" -eq 0 ]; then
    echo "=== Migration Incomplete ==="
  else
    echo "Note: ${#FAILED_VERIFICATION[@]} tool(s) were retained in Zerobrew due to verification failure." >&2
  fi
  exit 1
fi

echo "=== Migration Complete ==="
echo "All verified tools are now managed by Homebrew."
