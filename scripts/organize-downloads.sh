#!/usr/bin/env bash
set -euo pipefail

DOWNLOADS_DIR="${DOWNLOADS_DIR:-$HOME/Downloads}"
WORK_ROOT="${WORK_ROOT:-$HOME/work}"
SAFE_ROOT="$WORK_ROOT/data/downloads"
TMP_ROOT="$WORK_ROOT/tmp/downloads"
MODE="apply"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      MODE="dry-run"
      ;;
    -h|--help)
      cat <<'EOF'
Usage: organize-downloads.sh [--dry-run]

Moves files out of ~/Downloads into source/type-based folders.
Rules:
  - Enterprise WeCom-style files go to ~/work/data/downloads/wecom/YYYY/MM/
  - Browser software installers go to ~/work/tmp/downloads/browser/software/YYYY/MM/
  - Browser docs/archives go to browser/<type>/YYYY/MM/
  - Unknown items go to ~/work/tmp/downloads/unsorted/YYYY/MM/

The script never deletes files.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done

mkdir -p "$SAFE_ROOT/wecom" "$TMP_ROOT/browser" "$TMP_ROOT/unsorted"

is_hidden() {
  case "$(basename "$1")" in
    .* ) return 0 ;;
    * ) return 1 ;;
  esac
}

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

file_ext() {
  local name ext
  name="$(basename "$1")"
  ext="${name##*.}"
  if [ "$ext" = "$name" ]; then
    printf ''
  else
    lower "$ext"
  fi
}

quarantine_source() {
  local value
  value="$(xattr -p com.apple.quarantine "$1" 2>/dev/null || true)"
  if [ -z "$value" ]; then
    return 0
  fi
  printf '%s' "$value" | awk -F';' '{print tolower($3)}'
}

is_wecom_file() {
  local name source
  name="$(basename "$1")"
  source="$(quarantine_source "$1")"
  case "$name" in
    *企业微信*|*分享文件*|*微盘* ) return 0 ;;
  esac
  case "$source" in
    *wxwork*|*wecom*|*wechatwork*|*企业微信* ) return 0 ;;
  esac
  return 1
}

is_browser_source() {
  local source
  source="$(quarantine_source "$1")"
  case "$source" in
    edge|google\ chrome|chrome|safari|firefox|arc|chromium|brave* ) return 0 ;;
    * ) return 1 ;;
  esac
}

type_bucket() {
  local ext
  ext="$(file_ext "$1")"
  case "$ext" in
    dmg|pkg|app|msi|deb|rpm )
      printf 'software'
      ;;
    zip|7z|rar|tar|gz|bz2|xz )
      printf 'archives'
      ;;
    pdf|doc|docx|xls|xlsx|csv|tsv|ppt|pptx|md|txt|yaml|yml|json )
      printf 'documents'
      ;;
    png|jpg|jpeg|gif|webp|heic|svg )
      printf 'images'
      ;;
    mp4|mov|m4v|mkv|mp3|wav )
      printf 'media'
      ;;
    * )
      printf 'misc'
      ;;
  esac
}

month_path() {
  stat -f '%Sm' -t '%Y/%m' "$1"
}

unique_target() {
  local target dir base stem ext candidate n
  target="$1"
  if [ ! -e "$target" ]; then
    printf '%s' "$target"
    return 0
  fi

  dir="$(dirname "$target")"
  base="$(basename "$target")"
  if [[ "$base" == *.* ]]; then
    stem="${base%.*}"
    ext=".${base##*.}"
  else
    stem="$base"
    ext=""
  fi

  n=2
  while :; do
    candidate="$dir/${stem}_$n$ext"
    if [ ! -e "$candidate" ]; then
      printf '%s' "$candidate"
      return 0
    fi
    n=$((n + 1))
  done
}

move_item() {
  local src dest_root bucket month dest
  src="$1"
  month="$(month_path "$src")"

  if is_wecom_file "$src"; then
    dest_root="$SAFE_ROOT/wecom"
    bucket="attachments"
  elif is_browser_source "$src"; then
    dest_root="$TMP_ROOT/browser"
    bucket="$(type_bucket "$src")"
  else
    dest_root="$TMP_ROOT/unsorted"
    bucket="$(type_bucket "$src")"
  fi

  dest="$dest_root/$bucket/$month/$(basename "$src")"
  mkdir -p "$(dirname "$dest")"
  dest="$(unique_target "$dest")"

  if [ "$MODE" = "dry-run" ]; then
    echo "PLAN  $src -> $dest"
  else
    mv "$src" "$dest"
    echo "MOVED $src -> $dest"
  fi
}

organized_any=0
while IFS= read -r item; do
  organized_any=1
  move_item "$item"
done < <(find "$DOWNLOADS_DIR" -mindepth 1 -maxdepth 1 \( -type f -o -type d \) ! -name '.DS_Store' ! -name '.localized' -print)

if [ "$organized_any" -eq 0 ]; then
  echo "No downloads to organize."
fi
