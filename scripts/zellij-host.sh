#!/usr/bin/env bash
# zellij-host.sh — launchd-managed zellij session host
# If no attached client exists, opens Ghostty with zellij.
# If already attached (e.g. user is in Ghostty), just stays alive.
set -euo pipefail

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export TERM="${TERM:-xterm-256color}"

SESSION="${ZELLIJ_SESSION:-ai-work}"
LAYOUT="${ZELLIJ_DEFAULT_LAYOUT:-ai-work}"

# Ensure work dir exists (layout cwd). zellij fails silently if cwd missing.
mkdir -p "$HOME/work"

# Ensure work dir exists (layout cwd). zellij fails silently if cwd missing.
mkdir -p "$HOME/work"

# Already reachable (client attached)? Just keep the launchd job alive.
if zellij --session "$SESSION" action list-panes --json >/dev/null 2>&1; then
    exec sleep 86400
fi

ZJ_CMD="env -i HOME=\"$HOME\" PATH=\"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin\" TERM=\"${TERM:-xterm}\" /opt/homebrew/bin/zellij --session \"$SESSION\" --layout \"$LAYOUT\""

APPLESCRIPT_INPUT="$(ZJ_CMD="$ZJ_CMD" python3 - <<'PY'
import json
import os

print(json.dumps("exec " + os.environ["ZJ_CMD"] + "\n"))
PY
)"
APPLESCRIPT_WORKDIR="$(HOME="$HOME" python3 - <<'PY'
import json
import os

print(json.dumps(os.path.join(os.environ["HOME"], "work")))
PY
)"

# Open Ghostty (default terminal on this machine)
if [ -d "/Applications/Ghostty.app" ]; then
    osascript <<EOF
tell application "Ghostty"
    set cfg to new surface configuration
    set command of cfg to "/bin/zsh"
    set initial working directory of cfg to ${APPLESCRIPT_WORKDIR}
    set initial input of cfg to ${APPLESCRIPT_INPUT}
    set wait after command of cfg to true
    set newWindow to new window with configuration cfg
    activate window newWindow
end tell
EOF
elif [ -d "/Applications/Terminal.app" ]; then
    osascript -e "
        tell application \"Terminal\"
            activate
            do script \"${ZJ_CMD}\"
        end tell
    "
else
    echo "[$(date)] ERROR: no terminal app found" >&2
    exit 1
fi

# Wait for zellij to become reachable, then keep alive
for i in $(seq 1 30); do
    sleep 1
    if zellij --session "$SESSION" action list-panes --json >/dev/null 2>&1; then
        exec sleep 86400
    fi
done

echo "[$(date)] ERROR: zellij session $SESSION did not become ready in 30s" >&2
exit 1
