#!/usr/bin/env bash
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"; SOURCE="$(readlink "$SOURCE")"; [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"; done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
TEMPLATE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  cat <<EOF
Usage: install-imgup.sh [options]

Install imgup — CLI uploader for CloudFlare-ImgBed.

Creates ~/.local/bin/imgup symlink and validates private config.

Options:
  -h, --help    Show this help

Environment:
  MAC_BOOTSTRAP_PRIVATE_DIR    Override private config directory
EOF
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Resolve private config path (same pattern as other bootstrap scripts)
resolve_private() {
  local relative="imgbed/config.jsonc"

  if [ -n "${MAC_BOOTSTRAP_PRIVATE_DIR:-}" ] && [ -f "$MAC_BOOTSTRAP_PRIVATE_DIR/$relative" ]; then
    printf '%s\n' "$MAC_BOOTSTRAP_PRIVATE_DIR/$relative"
    return 0
  fi
  if [ -f "$TEMPLATE_DIR/../private/$relative" ]; then
    printf '%s\n' "$TEMPLATE_DIR/../private/$relative"
    return 0
  fi
  if [ -f "$TEMPLATE_DIR/private/$relative" ]; then
    printf '%s\n' "$TEMPLATE_DIR/private/$relative"
    return 0
  fi
  return 1
}

# Install symlink (idempotent: ln -sf always overwrites)
mkdir -p "$HOME/.local/bin"
ln -sf "$SCRIPT_DIR/imgup.sh" "$HOME/.local/bin/imgup"
chmod +x "$HOME/.local/bin/imgup"
echo "  ~/.local/bin/imgup -> scripts/imgup.sh"

# Validate private config exists and contains upload_api_key
CONFIG_FILE="$(resolve_private 2>/dev/null)" || true
if [ -z "$CONFIG_FILE" ] || [ ! -f "$CONFIG_FILE" ]; then
  echo "  WARN: private/imgbed/config.jsonc not found — create it with:" >&2
  echo "    { \"upload_api_key\": \"your-api-token\" }" >&2
  echo "  The imgup command will not work until this file exists." >&2
  exit 0
fi

API_KEY="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('upload_api_key',''))" < "$CONFIG_FILE" 2>/dev/null)" || true
if [ -z "$API_KEY" ]; then
  echo "  WARN: $CONFIG_FILE exists but upload_api_key is empty or unreadable" >&2
  echo "  The imgup command will not work until a valid key is set." >&2
  exit 0
fi

echo "  config: $CONFIG_FILE"
echo "  status: ready"
