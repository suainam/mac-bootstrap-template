#!/usr/bin/env bash
set -euo pipefail

PROFILE="${COLIMA_PROFILE:-www}"
CPUS="${COLIMA_CPUS:-4}"
MEMORY_GIB="${COLIMA_MEMORY_GIB:-6}"
DISK_GIB="${COLIMA_DISK_GIB:-80}"
PROXY_PORT="${COLIMA_PROXY_PORT:-}"
LOG_MAX_SIZE="${COLIMA_LOG_MAX_SIZE:-10m}"
LOG_MAX_FILE="${COLIMA_LOG_MAX_FILE:-3}"
DOCKER_CONTEXT="colima-${PROFILE}"
HOST_PROXY="http://127.0.0.1:${PROXY_PORT}"
GUEST_PROXY="http://host.lima.internal:${PROXY_PORT}"

usage() {
    cat <<'EOF'
Usage: scripts/colima-local.sh <start|stop|status|doctor>

Environment overrides:
  COLIMA_PROFILE          Profile name (default: www)
  COLIMA_CPUS             VM CPUs (default: 4)
  COLIMA_MEMORY_GIB       VM memory GiB (default: 6)
  COLIMA_DISK_GIB         Sparse data disk GiB (default: 80)
  COLIMA_PROXY_PORT       Host HTTP proxy port (required)
  COLIMA_LOG_MAX_SIZE     Docker json-file max size (default: 10m)
  COLIMA_LOG_MAX_FILE     Docker json-file rotated files (default: 3)
EOF
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "missing required command: $1" >&2
        exit 1
    }
}

check_host_proxy() {
    if [[ -z "${PROXY_PORT}" ]]; then
        echo "COLIMA_PROXY_PORT is required; keep machine-specific values in the private overlay" >&2
        exit 1
    fi
    if ! nc -z 127.0.0.1 "${PROXY_PORT}" >/dev/null 2>&1; then
        echo "proxy is not listening on 127.0.0.1:${PROXY_PORT}" >&2
        exit 1
    fi
}

profile_running() {
    colima --profile "${PROFILE}" status >/dev/null 2>&1
}

wait_for_docker() {
    local attempt
    for attempt in $(seq 1 30); do
        if docker --context "${DOCKER_CONTEXT}" info >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "docker context ${DOCKER_CONTEXT} did not become ready" >&2
    return 1
}

configure_logging() {
    local result
    result="$(colima --profile "${PROFILE}" ssh -- sudo env \
        LOG_MAX_SIZE="${LOG_MAX_SIZE}" LOG_MAX_FILE="${LOG_MAX_FILE}" \
        python3 -c '
import json
import os
from pathlib import Path

path = Path("/etc/docker/daemon.json")
config = json.loads(path.read_text()) if path.exists() else {}
desired = {
    "log-driver": "json-file",
    "log-opts": {
        "max-size": os.environ["LOG_MAX_SIZE"],
        "max-file": os.environ["LOG_MAX_FILE"],
    },
}
changed = any(config.get(key) != value for key, value in desired.items())
if changed:
    config.update(desired)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
print("changed" if changed else "unchanged")
')"

    if [[ "${result}" == *changed* && "${result}" != *unchanged* ]]; then
        colima --profile "${PROFILE}" ssh -- sudo systemctl restart docker
        wait_for_docker
    fi
}

start_profile() {
    require_command colima
    require_command docker
    require_command nc
    check_host_proxy

    if ! profile_running; then
        HTTP_PROXY="${HOST_PROXY}" \
        HTTPS_PROXY="${HOST_PROXY}" \
        NO_PROXY="localhost,127.0.0.1" \
            colima --profile "${PROFILE}" start \
                --cpus "${CPUS}" \
                --memory "${MEMORY_GIB}" \
                --disk "${DISK_GIB}" \
                --env "HTTP_PROXY=${GUEST_PROXY}" \
                --env "HTTPS_PROXY=${GUEST_PROXY}" \
                --env "NO_PROXY=localhost,127.0.0.1,host.lima.internal,host.docker.internal" \
                --save-config
    fi

    wait_for_docker
    configure_logging
    doctor_profile
}

doctor_profile() {
    require_command colima
    require_command docker
    require_command nc
    check_host_proxy
    profile_running || {
        echo "colima profile ${PROFILE} is not running" >&2
        exit 1
    }
    wait_for_docker
    colima --profile "${PROFILE}" ssh -- sudo env \
        LOG_MAX_SIZE="${LOG_MAX_SIZE}" LOG_MAX_FILE="${LOG_MAX_FILE}" \
        python3 -c '
import json
import os
from pathlib import Path

config = json.loads(Path("/etc/docker/daemon.json").read_text())
assert config.get("log-driver") == "json-file"
assert config.get("log-opts", {}).get("max-size") == os.environ["LOG_MAX_SIZE"]
assert config.get("log-opts", {}).get("max-file") == os.environ["LOG_MAX_FILE"]
'
    docker --context "${DOCKER_CONTEXT}" info \
        --format 'profile={{.Name}} arch={{.Architecture}} driver={{.Driver}} logging={{.LoggingDriver}}'
    echo "proxy=${HOST_PROXY} log=max-size:${LOG_MAX_SIZE},max-file:${LOG_MAX_FILE}"
}

case "${1:-}" in
    start)
        start_profile
        ;;
    stop)
        colima --profile "${PROFILE}" stop
        ;;
    status)
        colima --profile "${PROFILE}" status
        ;;
    doctor)
        doctor_profile
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
