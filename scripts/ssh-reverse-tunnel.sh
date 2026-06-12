#!/usr/bin/env bash
# ssh-reverse-tunnel.sh — launchd-managed SSH reverse tunnel
#
# Exposes local cc-switch proxy (127.0.0.1:15721) on the bastion's localhost,
# so remote tools can set ANTHROPIC_BASE_URL=http://127.0.0.1:15721 without
# installing any AI keys on the bastion.
#
# Requires an active ControlMaster socket for `dsliam` (established by the user
# logging in interactively). The daemon waits until the socket appears, then
# attaches the tunnel — no password/2FA needed after that.
#
# Override via env vars (set in ~/.zshrc.local or private overlay):
#   TUNNEL_SSH_HOST       — SSH Host alias (default: dsliam)
#   TUNNEL_REMOTE_PORT    — port to open on bastion (default: 15721)
#   TUNNEL_LOCAL_PORT     — local cc-switch port (default: 15721)
#   TUNNEL_SOCKET_WAIT    — seconds between socket-existence polls (default: 15)
set -euo pipefail

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SSH_HOST="${TUNNEL_SSH_HOST:-dsliam}"
REMOTE_PORT="${TUNNEL_REMOTE_PORT:-15721}"
LOCAL_PORT="${TUNNEL_LOCAL_PORT:-15721}"
SOCKET_WAIT="${TUNNEL_SOCKET_WAIT:-15}"

# ControlMaster socket path — mirrors ~/.ssh/config ControlPath pattern
# %r=user %h=hostname %p=port; resolve manually to avoid ssh dependency here
SSH_USER="16620000611"
SSH_HOST_REAL="dsliam.dslyy.com"
SSH_PORT="22"
SOCKET="${HOME}/.ssh/cm-${SSH_USER}@${SSH_HOST_REAL}:${SSH_PORT}"

LOG_DIR="${HOME}/Library/Logs/claude-daemon"
LOG="${LOG_DIR}/ssh-reverse-tunnel.log"
mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

log "=== ssh-reverse-tunnel starting (host=${SSH_HOST}, remote_port=${REMOTE_PORT}, local_port=${LOCAL_PORT}) ==="

# Wait until ControlMaster socket exists (user has logged in interactively)
until [ -S "$SOCKET" ]; do
    log "WAIT: ControlMaster socket not found at $SOCKET — waiting ${SOCKET_WAIT}s"
    sleep "$SOCKET_WAIT"
done

log "Socket found. Attaching reverse tunnel -R ${REMOTE_PORT}:127.0.0.1:${LOCAL_PORT}"

# -S: reuse existing ControlMaster socket (no new auth needed)
# -N: no remote command
# -T: no TTY
# -o ExitOnForwardFailure: fail fast if remote port already bound (triggers launchd restart)
exec ssh \
    -S "$SOCKET" \
    -N -T \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -R "${REMOTE_PORT}:127.0.0.1:${LOCAL_PORT}" \
    "$SSH_HOST"
