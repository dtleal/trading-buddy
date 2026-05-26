#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] Running Alembic migrations..."
alembic -c alembic.ini upgrade head

echo "[entrypoint] Starting: $*"
exec "$@"
