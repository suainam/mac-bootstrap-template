#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 1 || ! -f "$1/slide.svg" ]]; then
  echo "Usage from product_strategy root: $0 <lane_dir>" >&2
  exit 2
fi
lane=$(cd "$1" && pwd -P)
py=.venv/bin/python
if [[ ! -x "$py" ]]; then
  py=python3
fi
kit=topics/smart_assortment/04_outputs/ppt_master/templates/dashenlin/scripts/dashenlin_ppt_kit.py
chrome=${CHROME_BIN:-"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}
if [[ ! -x "$chrome" ]]; then
  echo "Chrome not found: $chrome" >&2
  exit 1
fi
"$py" "$kit" audit-svg "$lane" --check-copy

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
slide_url=$("$py" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).as_uri())' "$lane/slide.svg")
"$chrome" --headless=new --disable-gpu --user-data-dir="$scratch/profile" --allow-file-access-from-files \
  --hide-scrollbars --window-size=1280,720 --screenshot="$scratch/preview.png" "$slide_url"
"$py" - "$scratch/preview.png" <<'PY'
from pathlib import Path
import struct
import sys

with Path(sys.argv[1]).open("rb") as png:
    header = png.read(24)
if header[:8] != b"\x89PNG\r\n\x1a\n" or header[16:24] != struct.pack(">II", 1280, 720):
    raise SystemExit("Expected a 1280×720 PNG")
PY
mv "$scratch/preview.png" "$lane/preview.png"
printf '%s\n' "$lane/preview.png"
