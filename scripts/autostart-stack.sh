#!/usr/bin/env bash
# Autostart wrapper for trading-buddy.
#
# Invoked by ~/Library/LaunchAgents/com.trading-buddy.autostart.plist at login.
# Waits for the Docker daemon to become available (Docker Desktop may take a
# few seconds to start after login), then runs `make docker-up` from the repo.
#
# Logs land at ~/Library/Logs/trading-buddy/autostart.log so you can debug
# without keeping a terminal open.

set -uo pipefail

REPO_DIR="${TRADING_BUDDY_REPO:-/Users/diegoleal/trading-buddy}"
LOG_DIR="${HOME}/Library/Logs/trading-buddy"
LOG_FILE="${LOG_DIR}/autostart.log"
MAX_WAIT_SECONDS=180  # 3 minutes of patience for Docker Desktop to come up

mkdir -p "${LOG_DIR}"

log() {
    printf '[%s] %s\n' "$(date -u +'%Y-%m-%d %H:%M:%S UTC')" "$*" >>"${LOG_FILE}"
}

# Make sure Homebrew binaries (docker CLI, make, etc) are on PATH when launchd
# spawns us with a barebones environment.
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"

log "autostart-stack.sh starting (repo=${REPO_DIR})"

if [[ ! -d "${REPO_DIR}" ]]; then
    log "ERROR: repo dir not found at ${REPO_DIR}"
    exit 1
fi

# Wait for Docker daemon. `docker info` returns 0 only when the daemon
# responds. Poll every 2s.
deadline=$(( $(date +%s) + MAX_WAIT_SECONDS ))
while ! docker info >/dev/null 2>&1; do
    if (( $(date +%s) >= deadline )); then
        log "ERROR: Docker daemon did not become ready within ${MAX_WAIT_SECONDS}s"
        exit 2
    fi
    sleep 2
done

log "Docker is ready; bringing up the stack"

cd "${REPO_DIR}" || { log "ERROR: cd to ${REPO_DIR} failed"; exit 3; }

# `make docker-up` does `docker compose up -d --env-file .env`. If `.env`
# does not exist (fresh clone), fall back to compose without env-file so we
# at least try.
if [[ -f .env ]]; then
    make docker-up >>"${LOG_FILE}" 2>&1
else
    log "WARN: .env not found; running compose without --env-file"
    docker compose -f docker/docker-compose.yml up -d >>"${LOG_FILE}" 2>&1
fi

status=$?
if (( status == 0 )); then
    log "Stack is up. Frontend: http://localhost:3000 | API: http://localhost:8000"
else
    log "ERROR: docker compose up exited with status ${status}"
fi

exit "${status}"
