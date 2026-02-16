#!/bin/bash
set -e

# Start FastAPI backend
python3 /app/backend/app.py &

# Start watcher
python3 /app/scripts/watcher_v7.py &

# Wait for both
wait -n
