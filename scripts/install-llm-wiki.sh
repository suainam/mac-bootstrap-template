#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-install}"
LLM_WIKI_DIR="${LLM_WIKI_DIR:-$HOME/work/llm_wiki}"

usage() {
  cat <<'EOF'
Usage: install-llm-wiki.sh [install|build|mcp-build|doctor]

Runs the official llm_wiki local install/build commands inside LLM_WIKI_DIR.
Expected upstream steps:
  npm install
  npm run tauri build
  npm run mcp:build
EOF
}

require_cmd() {
  local tool="$1"
  local hint="$2"
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: $tool not installed. $hint" >&2
    exit 1
  fi
}

ensure_checkout() {
  if [ ! -d "$LLM_WIKI_DIR" ]; then
    echo "ERROR: LLM_WIKI_DIR not found: $LLM_WIKI_DIR" >&2
    exit 1
  fi
  if [ ! -f "$LLM_WIKI_DIR/package.json" ]; then
    echo "ERROR: missing package.json in $LLM_WIKI_DIR" >&2
    exit 1
  fi
}

check_node_major() {
  local major
  major="$(node -p 'process.versions.node.split(".")[0]')"
  if [ "${major:-0}" -lt 20 ]; then
    echo "ERROR: llm_wiki requires Node.js 20+ (found $(node --version))" >&2
    exit 1
  fi
}

check_rust_major_minor() {
  local major minor
  major="$(cargo --version | awk '{print $2}' | cut -d. -f1)"
  minor="$(cargo --version | awk '{print $2}' | cut -d. -f2)"
  if [ "${major:-0}" -lt 1 ] || { [ "${major:-0}" -eq 1 ] && [ "${minor:-0}" -lt 70 ]; }; then
    echo "ERROR: llm_wiki requires Rust 1.70+ (found $(cargo --version))" >&2
    exit 1
  fi
}

case "$ACTION" in
  install|build|mcp-build|doctor) ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    usage >&2
    exit 2
    ;;
esac

require_cmd node "Install Node.js 20+ first."
require_cmd npm "Install Node.js 20+ first."
require_cmd cargo "Install Rust 1.70+ first."
check_node_major
check_rust_major_minor
ensure_checkout

cd "$LLM_WIKI_DIR"
case "$ACTION" in
  install)
    npm install
    ;;
  build)
    npm run tauri build
    ;;
  mcp-build)
    npm run mcp:build
    ;;
  doctor)
    if [ -f "$LLM_WIKI_DIR/mcp-server/dist/index.js" ]; then
      echo "OK: llm_wiki MCP build artifact present"
    else
      echo "MISS: llm_wiki MCP build artifact missing (run: make llm-wiki-mcp-build)"
    fi
    echo "OK: llm_wiki checkout ready at $LLM_WIKI_DIR"
    ;;
esac
