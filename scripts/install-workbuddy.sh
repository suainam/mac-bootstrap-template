#!/usr/bin/env bash
set -euo pipefail

APP_BUNDLE_NAME="WorkBuddy AI.app"
WORKBUDDY_APP="/Applications/$APP_BUNDLE_NAME"
API_URL="https://www.codebuddy.ai/v2/update?platform=workbuddy-darwin-arm64"

WORK_DIR="$(mktemp -d)"
DMG_PATH="$WORK_DIR/WorkBuddy-install.dmg"
MOUNT_POINT="$WORK_DIR/mnt"

log()  { printf "\e[32m%s\e[0m\n" "$*"; }
warn() { printf "\e[33m%s\e[0m\n" "$*"; }
err()  { printf "\e[31m%s\e[0m\n" "$*"; }

cleanup() {
  hdiutil detach "$MOUNT_POINT" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

# The API reports a four-part version (5.5.2.37849279) while the bundle reports
# the three-part marketing version (5.5.2), so compare on the shared prefix.
version_is_current() {
  [ -n "$1" ] || return 1
  case "$LATEST_VERSION" in
    "$1"|"$1".*) return 0 ;;
    *) return 1 ;;
  esac
}

log "Fetching latest WorkBuddy info..."
API_JSON="$(curl -fsSL "$API_URL")"
LATEST_VERSION="$(printf '%s' "$API_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])")"
LATEST_SHA256="$(printf '%s' "$API_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['sha256hash'])")"
DMG_URL="$(printf '%s' "$API_JSON" | python3 -c "
import sys, json
url = json.load(sys.stdin)['url']
print(url[:-len('.zip')] + '.dmg' if url.endswith('.zip') else url)
")"

log "Latest version: $LATEST_VERSION"

if [ -d "$WORKBUDDY_APP" ]; then
  INFO_PLIST="$WORKBUDDY_APP/Contents/Info.plist"
  INSTALLED_VERSION="$(plutil -extract CFBundleShortVersionString raw "$INFO_PLIST" 2>/dev/null || echo "")"
  if version_is_current "$INSTALLED_VERSION"; then
    log "WorkBuddy $INSTALLED_VERSION already installed. Skipping."
    exit 0
  fi
  warn "Updating WorkBuddy ${INSTALLED_VERSION:-unknown} -> $LATEST_VERSION"
else
  log "WorkBuddy not found. Installing..."
fi

log "Downloading WorkBuddy $LATEST_VERSION..."
curl -fL -o "$DMG_PATH" "$DMG_URL"

log "Verifying checksum..."
DOWNLOADED_SHA256="$(shasum -a 256 "$DMG_PATH" | awk '{print $1}')"
if [ "$DOWNLOADED_SHA256" != "$LATEST_SHA256" ]; then
  err "SHA256 mismatch!"
  err "  Expected: $LATEST_SHA256"
  err "  Got:      $DOWNLOADED_SHA256"
  exit 1
fi
log "Checksum verified."

log "Installing..."
mkdir -p "$MOUNT_POINT"
hdiutil attach -nobrowse -readonly -mountpoint "$MOUNT_POINT" "$DMG_PATH" >/dev/null

APP_SOURCE="$(find "$MOUNT_POINT" -maxdepth 1 -name "$APP_BUNDLE_NAME" -type d | head -1)"
if [ -z "$APP_SOURCE" ]; then
  err "$APP_BUNDLE_NAME not found on mounted volume"
  exit 1
fi

rm -rf "$WORKBUDDY_APP"
ditto "$APP_SOURCE" "$WORKBUDDY_APP"
hdiutil detach "$MOUNT_POINT" >/dev/null 2>&1 || true

# Gatekeeper can flag the bundle as damaged when its verification round-trip
# fails; the vendor's Fix-Damage note prescribes clearing the quarantine flag.
xattr -dr com.apple.quarantine "$WORKBUDDY_APP" 2>/dev/null || true

log "WorkBuddy $LATEST_VERSION installed successfully."
log "App: $WORKBUDDY_APP"
