#!/usr/bin/env bash

run() {
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    printf 'DRY-RUN:'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

try_run() {
  if ! run "$@"; then
    echo "warn: command failed:"; printf '  %q' "$@"; printf '\n'
  fi
}

have() { command -v "$1" >/dev/null 2>&1; }

resolve_private_dir() {
  if [ -n "${MAC_BOOTSTRAP_PRIVATE_DIR:-}" ] && [ -d "$MAC_BOOTSTRAP_PRIVATE_DIR" ]; then
    printf '%s\n' "$MAC_BOOTSTRAP_PRIVATE_DIR"
    return 0
  fi
  if [ -n "${BOOTSTRAP:-}" ]; then
    local sibling_private
    sibling_private="$(cd "$BOOTSTRAP/.." 2>/dev/null && pwd)/private"
    if [ -d "$sibling_private" ]; then
      printf '%s\n' "$sibling_private"
      return 0
    fi
  fi
  if [ -d "private" ]; then
    printf '%s\n' "$(pwd)/private"
    return 0
  fi
  return 1
}

load_devspace_mcp_private_env() {
  local private_dir config_path
  private_dir="$(resolve_private_dir 2>/dev/null || true)"
  [ -n "$private_dir" ] || return 0
  config_path="$private_dir/agent/devspace.runtime.jsonc"
  [ -f "$config_path" ] || return 0

  local parsed
  parsed="$(python3 - "$config_path" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path


def strip_jsonc(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


path = Path(sys.argv[1])
data = json.loads(strip_jsonc(path.read_text(encoding="utf-8")))
exposure = data.get("exposure") or {}
base_url = (exposure.get("public_base_url") or "").rstrip("/")
enabled = exposure.get("mcp_enabled", bool(base_url))

if enabled and base_url:
    print("DEVSPACE_MCP_ENABLE=1")
    print(f"DEVSPACE_MCP_URL={base_url}/mcp")
else:
    print("DEVSPACE_MCP_ENABLE=0")
PY
)" || return 1

  local line key value
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    key="${line%%=*}"
    value="${line#*=}"
    export "$key=$value"
  done <<EOF
$parsed
EOF
}

capture_with_timeout() {
  local seconds="$1"
  shift
  python3 - "$seconds" "$@" <<'PY'
import subprocess
import sys

timeout = float(sys.argv[1])
cmd = sys.argv[2:]

try:
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
        check=False,
    )
    sys.stdout.write(result.stdout)
except subprocess.TimeoutExpired:
    pass
PY
}

replace_managed_block() {
  local file="$1" begin="$2" end="$3" block="$4"
  run mkdir -p "$(dirname "$file")"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: replace managed block in $file"
    return 0
  fi
  if [ ! -f "$file" ]; then
    printf '%s\n' "$block" > "$file"
    return 0
  fi

  python3 - "$file" "$begin" "$end" "$block" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
begin, end, block = sys.argv[2], sys.argv[3], sys.argv[4]
text = path.read_text()
start = text.find(begin)
finish = text.find(end)
if start != -1 and finish != -1 and finish >= start:
    finish += len(end)
    while finish < len(text) and text[finish] == "\n":
        finish += 1
    prefix = text[:start].rstrip()
    suffix = text[finish:].lstrip("\n")
    parts = [part for part in (prefix, block.rstrip(), suffix.rstrip()) if part]
    text = "\n\n".join(parts) + "\n"
else:
    text = text.rstrip() + "\n\n" + block.rstrip() + "\n"
path.write_text(text)
PY
}

download_and_run() {
  local url="$1"; shift
  local script_path; script_path="$(mktemp)"
  run curl -fsSL "$url" -o "$script_path"
  run chmod +x "$script_path"
  run bash "$script_path" "$@"
  if [ "${DRY_RUN:-0}" -eq 0 ]; then rm -f "$script_path"; fi
}

pick_rtk_source() {
  if [ -f "$CLAUDE_RTK" ]; then
    printf '%s\n' "$CLAUDE_RTK"
  elif [ -f "$CODEX_RTK" ]; then
    printf '%s\n' "$CODEX_RTK"
  else
    printf '\n'
  fi
}

write_markdown_file() {
  local path="$1" body="$2"
  run mkdir -p "$(dirname "$path")"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: write markdown file $path"
  else
    printf '%s\n' "$body" > "$path"
  fi
}

write_reference_file() {
  local path="$1"
  shift
  run mkdir -p "$(dirname "$path")"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: write reference file $path"
  else
    printf '%s\n' "$@" > "$path"
  fi
}

render_runtime_rules_doc() {
  local title="$1"
  local rtk_source="$2"
  local rtk_ref="${rtk_source:-$CODEX_RTK}"

  cat <<EOF
<!-- Generated by install-agent-tooling.sh — do not edit manually -->
<!-- Edit canonical source at $RULES_FILE -->

# $title

## 12 Rules Summary

Think before coding. Prefer the simplest change. Touch only what is needed.
Read before write. Match local conventions. Verify intent with tests.
Checkpoint after meaningful steps. Fail loud on uncertainty or skipped work.

## RTK

Use \`rtk\` for shell commands when available. Canonical reference:
\`$rtk_ref\`

## CRG / Docs

Prefer \`codebase-memory-mcp\` and \`context7\` before grep for code discovery.

Canonical rules:
- \`$RULES_FILE\`
- \`$rtk_ref\`

Official docs:
- Claude: https://code.claude.com/docs/en/configuration
- Codex: https://developers.openai.com/learn/docs-mcp
- OpenCode: https://open-code.ai/en/docs/rules
- Pi: https://pi.dev/docs/latest/usage
- Reasonix: https://esengine.github.io/DeepSeek-Reasonix/configuration.html
- Antigravity: https://antigravity.google/docs/rules-workflows
EOF
}

ensure_file_contains() {
  local path="$1" needle="$2" addition="$3"
  run mkdir -p "$(dirname "$path")"
  if [ "${DRY_RUN:-0}" -eq 1 ]; then
    echo "DRY-RUN: ensure $path contains $needle"
    return 0
  fi
  if [ ! -f "$path" ]; then
    printf '%s\n' "$addition" > "$path"
    return 0
  fi
  if ! grep -Fq "$needle" "$path" 2>/dev/null; then
    printf '\n%s\n' "$addition" >> "$path"
  fi
}

CRG_BIN() { command -v codebase-memory-mcp 2>/dev/null; }
