#!/usr/bin/env bash
# install-clash.sh — Download and install Clash Verge via GitHub mirror
# Zero-dependency bootstrap: works without any proxy pre-installed.
# Uses GitHub mirror proxies to download Clash Verge, then installs it.
set -euo pipefail

# --- Config ---
APP_NAME="Clash Verge"
APP_PATH="/Applications/Clash Verge.app"
REPO="clash-verge-rev/clash-verge-rev"

# GitHub mirror proxies (tried in order, first success wins)
MIRRORS=(
  "https://gh-proxy.com/"
  "https://ui.ghproxy.cc/"
  "https://github.akams.cn/"
  "https://www.gitwarp.com/"
)

# Fallback: direct GitHub (works if user already has proxy)
DIRECT=""

DRY_RUN=0
FORCE=0
DOWNLOAD_DIR="/tmp/clash-verge-install"

usage() {
  cat <<'EOF'
Usage: scripts/install-clash.sh [options]

Download and install Clash Verge from GitHub via mirror proxies.
No proxy required — mirrors bypass GFW for the download.

Options:
  --dry-run    Print commands without running them.
  --force      Reinstall even if already installed.
  -h, --help   Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --force) FORCE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# --- Helpers ---
log()  { echo "[install-clash] $*"; }
err()  { echo "[install-clash] ERROR: $*" >&2; }
run()  {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRY-RUN:'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

# --- Detect architecture ---
detect_arch() {
  local arch
  arch="$(uname -m)"
  case "$arch" in
    arm64)  echo "aarch64" ;;
    x86_64) echo "x64" ;;
    *)      err "Unsupported architecture: $arch"; exit 1 ;;
  esac
}

# --- Get latest release version from GitHub API ---
get_latest_version() {
  local api_url="https://api.github.com/repos/${REPO}/releases/latest"
  local mirrors_api=(
    "https://gh-proxy.com/"
    "https://ui.ghproxy.cc/"
  )

  # Try direct first
  local version
  version=$(curl -sL --connect-timeout 10 "$api_url" 2>/dev/null \
    | grep '"tag_name"' | head -1 | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/' || true)

  if [ -n "$version" ]; then
    echo "$version"
    return 0
  fi

  # Try mirrors
  for mirror in "${mirrors_api[@]}"; do
    version=$(curl -sL --connect-timeout 10 "${mirror}${api_url}" 2>/dev/null \
      | grep '"tag_name"' | head -1 | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/' || true)
    if [ -n "$version" ]; then
      echo "$version"
      return 0
    fi
  done

  # Hardcoded fallback
  echo "v2.4.7"
}

# --- Build download URL ---
build_download_url() {
  local version="$1"
  local arch="$2"
  local filename="Clash.Verge_${version#v}_${arch}.dmg"
  echo "https://github.com/${REPO}/releases/download/${version}/${filename}"
}

# --- Download with mirror fallback ---
download_with_mirrors() {
  local url="$1"
  local output="$2"

  run mkdir -p "$(dirname "$output")"

  for mirror in "${MIRRORS[@]}"; do
    local mirror_url="${mirror}${url}"
    log "Trying: ${mirror}..."
    if run curl -fSL --connect-timeout 15 --max-time 300 -o "$output" "$mirror_url" 2>/dev/null; then
      if [ -s "$output" ]; then
        log "Downloaded via ${mirror}"
        return 0
      fi
    fi
    rm -f "$output" 2>/dev/null
  done

  # Try direct as last resort
  log "Trying: direct GitHub..."
  if run curl -fSL --connect-timeout 15 --max-time 300 -o "$output" "$url" 2>/dev/null; then
    if [ -s "$output" ]; then
      log "Downloaded via direct GitHub"
      return 0
    fi
  fi

  rm -f "$output" 2>/dev/null
  err "All download attempts failed"
  return 1
}

# --- Verify SHA256 (from GitHub release) ---
verify_checksum() {
  local file="$1"
  local version="$2"

  # Try to download checksums file
  local checksum_url="https://github.com/${REPO}/releases/download/${version}/sha256sum.txt"
  local checksum_file="/tmp/clash-verge-checksums.txt"

  for mirror in "${MIRRORS[@]}" ""; do
    local try_url="${mirror}${checksum_url}"
    if curl -fsSL --connect-timeout 10 -o "$checksum_file" "$try_url" 2>/dev/null; then
      break
    fi
  done

  if [ ! -f "$checksum_file" ]; then
    log "WARNING: Could not download checksum file, skipping verification"
    return 0
  fi

  local filename
  filename="$(basename "$file")"
  local expected
  expected=$(grep "$filename" "$checksum_file" 2>/dev/null | awk '{print $1}' || true)

  if [ -z "$expected" ]; then
    log "WARNING: No checksum found for $filename, skipping verification"
    rm -f "$checksum_file"
    return 0
  fi

  local actual
  actual=$(shasum -a 256 "$file" | awk '{print $1}')

  rm -f "$checksum_file"

  if [ "$expected" = "$actual" ]; then
    log "SHA256 verified: $actual"
    return 0
  else
    err "SHA256 mismatch: expected=$expected actual=$actual"
    return 1
  fi
}

# --- Install .app from DMG ---
install_from_dmg() {
  local dmg_path="$1"

  log "Mounting DMG..."
  local mount_point
  mount_point=$(hdiutil attach "$dmg_path" -nobrowse -quiet 2>/dev/null \
    | grep "/Volumes" | tail -1 | awk '{print $NF}')

  if [ -z "$mount_point" ]; then
    err "Failed to mount DMG"
    return 1
  fi

  log "Mounted at: $mount_point"

  # Find .app in mount point
  local app_source
  app_source=$(find "$mount_point" -maxdepth 1 -name "*.app" -type d | head -1)

  if [ -z "$app_source" ]; then
    err "No .app found in DMG"
    hdiutil detach "$mount_point" -quiet 2>/dev/null || true
    return 1
  fi

  log "Installing: $app_source -> $APP_PATH"
  run cp -R "$app_source" "$APP_PATH"

  log "Unmounting DMG..."
  hdiutil detach "$mount_point" -quiet 2>/dev/null || true

  log "Installed to $APP_PATH"
}

# --- Main ---
main() {
  log "=== Clash Verge Installer ==="

  # Check if already installed
  if [ -d "$APP_PATH" ] && [ "$FORCE" -eq 0 ]; then
    log "$APP_NAME is already installed at $APP_PATH"
    log "Use --force to reinstall"
    exit 0
  fi

  # Detect arch
  local arch
  arch=$(detect_arch)
  log "Architecture: $arch"

  # Get latest version
  local version
  version=$(get_latest_version)
  log "Latest version: $version"

  # Build URL
  local url
  url=$(build_download_url "$version" "$arch")
  log "Download URL: $url"

  # Download
  local dmg_path="${DOWNLOAD_DIR}/Clash.Verge_${version#v}_${arch}.dmg"
  download_with_mirrors "$url" "$dmg_path"

  # Verify
  verify_checksum "$dmg_path" "$version" || {
    err "Checksum verification failed"
    rm -f "$dmg_path"
    exit 1
  }

  # Install
  install_from_dmg "$dmg_path"

  # Cleanup
  rm -rf "$DOWNLOAD_DIR"

  log "=== Done! ==="
  log "Launch $APP_NAME from Applications or run:"
  log "  open \"$APP_PATH\""
}

main "$@"
