#!/usr/bin/env bash
# Fix Cline navigator compatibility error
set -euo pipefail

echo "=== Fixing Cline Extension ==="

# Uninstall old claude-dev
echo "Uninstalling saoudrizwan.claude-dev..."
docker exec code-server code-server --uninstall-extension saoudrizwan.claude-dev || true

# Install official cline extension
echo "Installing saoudrizwan.cline..."
docker exec code-server code-server --install-extension saoudrizwan.cline

# Verify
echo ""
echo "Verification:"
docker exec code-server sh -c 'ls -la /root/.local/share/code-server/extensions | grep -i cline'

echo ""
echo "✅ Done. Reload code-server window to activate."
