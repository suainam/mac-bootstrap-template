#!/usr/bin/env bash

manifest_get() {
  local key="$1"
  python3 - "$MANIFEST" "$key" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
value = manifest
for part in sys.argv[2].split("."):
    value = value[part]
if isinstance(value, (dict, list)):
    print(json.dumps(value))
else:
    print(value)
PY
}

expand_path() {
  local path="$1"
  path="${path/#\~/$HOME}"
  path="${path//\$\{HOME\}/$HOME}"
  path="${path//\$\{BOOTSTRAP\}/$BOOTSTRAP}"
  printf '%s\n' "$path"
}

canonical_path() {
  local rel
  rel="$(manifest_get "$1")"
  printf '%s\n' "$BOOTSTRAP/$rel"
}

json_array_to_lines() {
  python3 - <<'PY'
import json
import sys

for item in json.loads(sys.stdin.read() or "[]"):
    print(item)
PY
}

json_get_path() {
  local query="$1"
  expand_path "$(manifest_get "$query")"
}
