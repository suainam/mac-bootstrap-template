#!/usr/bin/env bash
set -euo pipefail

cleanup_managed_profile() {
  local file="$1"
  [ -f "$file" ] || return 0

  python3 - "$file" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
needle = '\n\n# Added by Antigravity CLI installer\nexport PATH="$HOME/.local/bin:$PATH"\n'
if needle in text:
    path.write_text(text.replace(needle, '\n'))
PY
}

if command -v agy >/dev/null 2>&1 || command -v antigravity >/dev/null 2>&1; then
  cleanup_managed_profile "$HOME/work/config/mac-bootstrap/shell/zprofile"
  cleanup_managed_profile "$HOME/work/config/mac-bootstrap/shell/bash_profile"
  echo "Antigravity CLI already installed."
  exit 0
fi

curl -fsSL https://antigravity.google/cli/install.sh | bash

# The bootstrap repo already manages PATH for ~/.local/bin. If the official
# installer touched symlinked dotfiles, normalize them back to repo state.
cleanup_managed_profile "$HOME/work/config/mac-bootstrap/shell/zprofile"
cleanup_managed_profile "$HOME/work/config/mac-bootstrap/shell/bash_profile"
