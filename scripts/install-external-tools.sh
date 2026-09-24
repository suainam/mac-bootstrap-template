#!/usr/bin/env bash
# install-external-tools.sh — Idempotently install and verify tools declared in manifests/external-tools.json
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$DIR/manifests/external-tools.json"

if [ ! -f "$MANIFEST" ]; then
  echo "Manifest not found: $MANIFEST" >&2
  exit 1
fi

echo "=== Processing External Tools Manifest ($MANIFEST) ==="

# 1. NPM globals
if command -v npm >/dev/null 2>&1; then
  echo "--- Verifying NPM Globals ---"
  "$DIR/scripts/install-npm-global-packages.sh"
else
  echo "  SKIP: npm not installed yet."
fi

# 2. Standalone Binaries
echo "--- Verifying Standalone Binaries ---"
mkdir -p "$HOME/.local/bin"

python3 -c "
import json, os, subprocess, sys
from pathlib import Path

manifest_path = Path('$MANIFEST')
with open(manifest_path, encoding='utf-8') as f:
    data = json.load(f)

for item in data.get('standalone_binaries', []):
    name = item.get('name')
    target = os.path.expanduser(item.get('target', ''))
    installer = item.get('installer')
    install_cmd = item.get('install_cmd')

    if os.path.exists(target) and os.access(target, os.X_OK):
        print(f'  OK   {name} ({target})')
        continue

    print(f'  INSTALLING {name}...')
    if installer:
        installer_path = Path('$DIR') / installer
        if installer_path.exists():
            subprocess.run(['bash', str(installer_path)], check=True)
        else:
            print(f'  ERROR: Installer not found: {installer_path}', file=sys.stderr)
    elif install_cmd:
        subprocess.run(install_cmd, shell=True, check=True)
    else:
        print(f'  INFO {name} requires manual installation at {target}')
"

echo "=== External Tools Manifest Complete ==="
