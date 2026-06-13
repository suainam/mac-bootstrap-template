#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v code >/dev/null 2>&1; then
  echo "VS Code CLI 'code' not found; skip extension install."
  echo "Open VS Code once and run 'Shell Command: Install code command in PATH' if needed."
  exit 0
fi

while IFS= read -r extension; do
  case "$extension" in
    ""|\#*)
      continue
      ;;
  esac
  code --install-extension "$extension" --force
done < "$DIR/extensions.txt"
