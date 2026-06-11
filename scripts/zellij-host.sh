#!/usr/bin/env bash
# zellij-host.sh — launchd-managed zellij session host
# If no attached client exists, opens iTerm2 with zellij.
# If already attached (e.g. user is in iTerm2), just stays alive.
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

# Session exists but detached — open terminal to attach
if zellij list-sessions 2>/dev/null | grep -q "$SESSION"; then
    ZJ_CMD="zellij attach $SESSION"
else
    ZJ_CMD="zellij attach --create $SESSION --layout $LAYOUT"
fi

# Open iTerm2 (default terminal on this machine)
if [ -d "/Applications/iTerm.app" ]; then
    osascript -e "
        tell application \"iTerm\"
            activate
            set newWindow to (create window with default profile)
            tell current session of newWindow
                write text \"${ZJ_CMD}\"
            end tell
        end tell
    "
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
