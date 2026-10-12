#!/usr/bin/env bash
set -euo pipefail

# Install or verify AuroraPixel/jev-browser-use prebuilt binary and unpacked Chrome MV3 extension.
# Usage:
#   ./scripts/install-jev-browser-use.sh [--force]

FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    -h|--help)
      echo "Usage: install-jev-browser-use.sh [--force]"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

REPO="${JEV_BROWSER_USE_REPO:-AuroraPixel/jev-browser-use}"
VERSION="${JEV_BROWSER_USE_VERSION:-0.1.0}"
BASE_URL="${JEV_BROWSER_USE_DOWNLOAD_BASE:-https://github.com/${REPO}/releases/download/v${VERSION}}"

BIN_DEST="${HOME}/.local/bin/jev-browser-use"
RUNTIME_HOME="${JEV_BROWSER_USE_HOME:-${HOME}/.jev-browser-use/v1}"
EXT_DIR="${RUNTIME_HOME}/extension"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH_RAW="$(uname -m)"
case "$ARCH_RAW" in
  arm64|aarch64) ARCH="arm64" ;;
  x86_64|amd64) ARCH="x64" ;;
  *) echo "Unsupported architecture: $ARCH_RAW" >&2; exit 1 ;;
esac

if [ "$OS" != "darwin" ] && [ "$OS" != "linux" ]; then
  echo "Unsupported OS for jev-browser-use prebuilt binary: $OS" >&2
  exit 1
fi

ASSET="jev-browser-use-${OS}-${ARCH}"
EXT_ZIP="jev-browser-use-extension-${VERSION}.zip"

if [ "$FORCE" -eq 0 ] && [ -x "$BIN_DEST" ] && [ -f "$EXT_DIR/manifest.json" ]; then
  echo "  OK   jev-browser-use already installed ($BIN_DEST, extension: $EXT_DIR)"
  exit 0
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT

echo "  Downloading jev-browser-use v${VERSION} (${ASSET}) and SHA256SUMS..."
curl -fsSL "${BASE_URL}/SHA256SUMS" -o "${TMP_DIR}/SHA256SUMS"
curl -fsSL "${BASE_URL}/${ASSET}" -o "${TMP_DIR}/${ASSET}"
curl -fsSL "${BASE_URL}/${EXT_ZIP}" -o "${TMP_DIR}/${EXT_ZIP}"

python3 - "$TMP_DIR" "$ASSET" "$EXT_ZIP" <<'PY'
import hashlib
import sys
from pathlib import Path

tmp_dir = Path(sys.argv[1])
targets = sys.argv[2:]
sums_text = (tmp_dir / "SHA256SUMS").read_text(encoding="utf-8")

expected_map = {}
for line in sums_text.splitlines():
    parts = line.strip().split()
    if len(parts) >= 2:
        digest = parts[0].lower()
        name = parts[-1].lstrip("*")
        expected_map[name] = digest

for name in targets:
    if name not in expected_map:
        raise SystemExit(f"ERROR: {name} missing from SHA256SUMS")
    actual = hashlib.sha256((tmp_dir / name).read_bytes()).hexdigest().lower()
    if actual != expected_map[name]:
        raise SystemExit(f"ERROR: SHA256 mismatch for {name}: expected {expected_map[name]}, got {actual}")
    print(f"  VERIFIED sha256 {name} ({actual[:12]}...)")
PY

mkdir -p "$(dirname "$BIN_DEST")"
install -m 0755 "${TMP_DIR}/${ASSET}" "$BIN_DEST"

mkdir -p "$EXT_DIR"
rm -rf "${EXT_DIR:?}/"*
unzip -q "${TMP_DIR}/${EXT_ZIP}" -d "$EXT_DIR"

echo "  INSTALLED binary:    $BIN_DEST ($("$BIN_DEST" --version))"
echo "  INSTALLED extension: $EXT_DIR"
