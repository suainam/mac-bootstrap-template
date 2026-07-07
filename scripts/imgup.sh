#!/usr/bin/env bash
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"; SOURCE="$(readlink "$SOURCE")"; [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"; done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
TEMPLATE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMGBED_URL="https://img.saui.dpdns.org"

usage() {
  cat <<EOF
Usage: imgup [options] [<file...>]

Upload images to CloudFlare-ImgBed.

Options:
  -p, --paste       Upload image from clipboard instead of files
  -m, --markdown    Output as Markdown image syntax ![](url)
  -q, --quiet       Suppress clipboard copy and extra output
  -h, --help        Show this help

Examples:
  imgup screenshot.png
  imgup -m screenshot.png
  imgup -p -m       Upload clipboard image, copy Markdown link
  imgup image1.png image2.jpg
EOF
  exit 0
}

die() {
  echo "Error: $*" >&2
  exit 1
}

cleanup() {
  [ -n "${TMPFILE:-}" ] && rm -f "$TMPFILE"
}
trap cleanup EXIT

resolve_imgbed_config() {
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

PASTE=false
MARKDOWN=false
QUIET=false

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--paste) PASTE=true; shift ;;
    -m|--markdown) MARKDOWN=true; shift ;;
    -q|--quiet) QUIET=true; shift ;;
    -h|--help) usage ;;
    --) shift; break ;;
    -*) die "Unknown option: $1 (use -h for help)" ;;
    *) break ;;
  esac
done

CONFIG_FILE="$(resolve_imgbed_config)" || die "Cannot find private/imgbed/config.jsonc"
API_KEY="$(python3 -c "import json,sys; print(json.load(sys.stdin)['upload_api_key'])" < "$CONFIG_FILE")"
[ -z "$API_KEY" ] && die "upload_api_key is empty in config"

FILES=()

if [ "$PASTE" = true ]; then
  [ $# -gt 0 ] && die "Cannot combine --paste with file arguments"
  TMPFILE="$(mktemp /tmp/imgup-XXXXXXXX)"
  if command -v pngpaste &>/dev/null; then
    pngpaste "$TMPFILE" || die "Clipboard does not contain an image"
  else
    die "pngpaste not found. Run: brew install pngpaste"
  fi
  HASH="$(shasum -a 256 "$TMPFILE" | head -c 8)"
  mv "$TMPFILE" "/tmp/imgup-$HASH.png"
  TMPFILE="/tmp/imgup-$HASH.png"
  FILES+=("$TMPFILE")
else
  [ $# -eq 0 ] && die "Usage: imgup <file...> (use -h for help)"
  FILES=("$@")
fi

UPLOADED=()
for file in "${FILES[@]}"; do
  [ ! -f "$file" ] && die "File not found: $file"

  resp="$(curl -sS "$IMGBED_URL/upload?returnFormat=full" \
    -H "Authorization: Bearer $API_KEY" \
    -F "file=@$file")"

  url="$(python3 -c "import sys,json; print(json.load(sys.stdin)[0]['src'])" <<< "$resp")"
  [ -z "$url" ] && die "Upload failed for: $file (empty response)"

  if [ "$MARKDOWN" = true ]; then
    output="![]($url)"
  else
    output="$url"
  fi

  echo "$output"
  UPLOADED+=("$output")
done

if [ "$QUIET" = false ] && [ ${#UPLOADED[@]} -gt 0 ]; then
  printf '%s' "${UPLOADED[-1]}" | pbcopy
  echo "  -> copied to clipboard" >&2
fi
