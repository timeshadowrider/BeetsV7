#!/usr/bin/env bash
set -e

if [ ! -f "/data/beets-library.blb" ]; then
  echo "[entrypoint] No beets library found, creating empty DB..."
  touch /data/beets-library.blb
fi

echo "[entrypoint] Starting API on port ${APP_PORT:-7080}..."
exec uvicorn backend.app:app --host 0.0.0.0 --port "${APP_PORT:-7080}"
