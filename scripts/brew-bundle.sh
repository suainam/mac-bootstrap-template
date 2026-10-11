#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -gt 0 ] && [ "$1" != "install" ]; then
  echo "Usage: $0 [install]" >&2
  exit 2
fi

DIR="$(cd "$(dirname "$0")/.." && pwd)"
export MAC_BOOTSTRAP_PRIVATE_DIR="${MAC_BOOTSTRAP_PRIVATE_DIR:-$DIR/../private}"
export MAC_BOOTSTRAP_PROFILE="${MAC_BOOTSTRAP_PROFILE:-$("$DIR/scripts/resolve-profile.sh")}"
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

# Homebrew evaluates Ruby/profile inclusions; zb's line parser cannot do so.
# Taps, casks, npm, services and post-install hooks remain Homebrew-owned.
if ! command -v zb >/dev/null 2>&1; then
  brew install zerobrewhq/zerobrew/zerobrew
fi
TMP_FORMULAS="$(mktemp)"
TMP_INFO="$(mktemp)"
if ! command -v jq >/dev/null 2>&1; then
  brew install jq
fi
trap 'rm -f "$TMP_FORMULAS" "$TMP_INFO"' EXIT
brew bundle list --file="$DIR/Brewfile" --formula > "$TMP_FORMULAS"
FORMULAS=()
while IFS= read -r formula; do
  [ -n "$formula" ] && FORMULAS+=("$formula")
done < "$TMP_FORMULAS"
if [ "${#FORMULAS[@]}" -gt 0 ]; then
  brew info --json=v2 "${FORMULAS[@]}" > "$TMP_INFO"
  # Only standalone bottles can transfer ownership without breaking Brew dependents.
  jq -r '.formulae[] | select(.tap == "homebrew/core" and .versions.bottle == true and .post_install_defined != true and ((.post_install_steps // []) | length) == 0 and .service == null and (.dependencies | length) == 0 and ([.bottle.stable.files[].cellar] | all(. == ":any_skip_relocation"))) | .name' "$TMP_INFO" > "$TMP_FORMULAS"
fi
ZB_FORMULAS=()
while IFS= read -r formula; do
  [ -n "$formula" ] || continue
  case " ${HOMEBREW_BUNDLE_BREW_SKIP:-} " in
    *" $formula "*) continue ;;
  esac
  ZB_FORMULAS+=("$formula")
done < "$TMP_FORMULAS"
if [ "${#ZB_FORMULAS[@]}" -gt 0 ]; then
  zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" init --no-modify-path
  zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" install "${ZB_FORMULAS[@]}"
  zb --root "$ZEROBREW_ROOT" --prefix "$ZEROBREW_PREFIX" doctor
  # Docker discovers plugins separately from PATH; expose the relocated bottles.
  for formula in "${ZB_FORMULAS[@]}"; do
    case "$formula" in
      docker-buildx|docker-compose)
        mkdir -p "${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins"
        ln -sfn "$ZEROBREW_PREFIX/lib/docker/cli-plugins/$formula" "${DOCKER_CONFIG:-$HOME/.docker}/cli-plugins/$formula"
        ;;
    esac
  done
  BREW_INSTALLED="$(brew list --formula)"
  for formula in "${ZB_FORMULAS[@]}"; do
    if ! printf '%s\n' "$BREW_INSTALLED" | /usr/bin/grep -Fxq "$formula"; then
      continue
    fi
    dependents="$(brew uses --installed "$formula")"
    if [ -n "$dependents" ]; then
      echo "Cannot transfer $formula: still required by Homebrew: $dependents" >&2
      exit 1
    fi
    brew uninstall "$formula"
  done
  export HOMEBREW_BUNDLE_BREW_SKIP="${HOMEBREW_BUNDLE_BREW_SKIP:-} ${ZB_FORMULAS[*]}"
fi
brew bundle install --no-upgrade --file="$DIR/Brewfile"
