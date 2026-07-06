#!/usr/bin/env bash
set -euo pipefail

WORKBUDDY_APP="/Applications/WorkBuddy.app"
API_URL="https://www.codebuddy.cn/v2/update?platform=workbuddy-darwin-arm64"
DMG_PATH="/tmp/WorkBuddy-install.dmg"

log()  { printf "\e[32m%s\e[0m\n" "$*"; }
warn() { printf "\e[33m%s\e[0m\n" "$*"; }
err()  { printf "\e[31m%s\e[0m\n" "$*"; }

# Get latest version info from API
log "Fetching latest WorkBuddy info..."
API_JSON=$(curl -sL "$API_URL")
LATEST_VERSION=$(echo "$API_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])")
LATEST_SHA256=$(echo "$API_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['sha256hash'])")
DMG_URL=$(echo "$API_JSON" | python3 -c "
import sys,json
url = json.load(sys.stdin)['url'].replace('.zip','.dmg')
print(url)
")

log "Latest version: $LATEST_VERSION"

# Check if already installed and up-to-date
if [ -d "$WORKBUDDY_APP" ]; then
  INFO_PLIST="$WORKBUDDY_APP/Contents/Info.plist"
  if [ -f "$INFO_PLIST" ]; then
    INSTALLED_VERSION=$(plutil -p "$INFO_PLIST" 2>/dev/null | grep -i 'CFBundleShortVersionString\|CFBundleVersion' | head -1 | awk -F'"' '{print $2}' || echo "")
    if [ "$INSTALLED_VERSION" = "$LATEST_VERSION" ]; then
      log "WorkBuddy $LATEST_VERSION already installed. Skipping."
      exit 0
    fi
    warn "Updating WorkBuddy $INSTALLED_VERSION -> $LATEST_VERSION"
  fi
else
  log "WorkBuddy not found. Installing..."
fi

# Download DMG
log "Downloading WorkBuddy $LATEST_VERSION..."
curl -L -o "$DMG_PATH" "$DMG_URL"

# Verify SHA256
log "Verifying checksum..."
DOWNLOADED_SHA256=$(shasum -a 256 "$DMG_PATH" | awk '{print $1}')
if [ "$DOWNLOADED_SHA256" != "$LATEST_SHA256" ]; then
  err "SHA256 mismatch!"
  err "  Expected: $LATEST_SHA256"
  err "  Got:      $DOWNLOADED_SHA256"
  rm -f "$DMG_PATH"
  exit 1
fi
log "Checksum verified."

# Mount and install
log "Installing..."
VOLUME=$(hdiutil attach "$DMG_PATH" | tail -1 | awk '{print $NF}')
if [ -z "$VOLUME" ] || [ ! -d "$VOLUME" ]; then
  err "Failed to mount DMG"
  rm -f "$DMG_PATH"
  exit 1
fi

# The volume name may contain the version, e.g. "WorkBuddy 5.1.7-arm64"
APP_SOURCE=$(find "$VOLUME" -maxdepth 1 -name "WorkBuddy.app" -type d | head -1)
if [ -z "$APP_SOURCE" ]; then
  err "WorkBuddy.app not found on mounted volume"
  hdiutil detach "$VOLUME" 2>/dev/null || true
  rm -f "$DMG_PATH"
  exit 1
fi

rm -rf "$WORKBUDDY_APP"
cp -R "$APP_SOURCE" /Applications/
hdiutil detach "$VOLUME" 2>/dev/null || true
rm -f "$DMG_PATH"

log "WorkBuddy $LATEST_VERSION installed successfully."
log "App: $WORKBUDDY_APP"
