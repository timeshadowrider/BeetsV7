#!/usr/bin/env bash
# deploy.sh — Sync the BeetsV7 git repo to the live server deployment path.
#
# Safe to re-run: preserves .env, data/, config/, static/, and public/assets/.
# Run this from the repo root on the host machine (not inside Docker).
#
# Usage:  bash deploy.sh [--dry-run]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="/srv/dev-disk-by-uuid-306c14f2-0239-4b1e-8775-915dfdd88bd0/NVME/Docket_Configs/Beets-v7"

DRY_RUN=""
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN="--dry-run"
    echo "[DEPLOY] DRY RUN — no files will be changed"
fi

if [[ ! -d "$DEPLOY_DIR" ]]; then
    echo "[ERROR] Deploy target not found: $DEPLOY_DIR"
    echo "        Are you running this on the correct host?"
    exit 1
fi

echo "[DEPLOY] Source : $REPO_DIR"
echo "[DEPLOY] Target : $DEPLOY_DIR"
echo ""

rsync -av --checksum $DRY_RUN \
    --exclude='.git/' \
    --exclude='.env' \
    --exclude='docker/.env' \
    --exclude='data/' \
    --exclude='config/' \
    --exclude='static/' \
    --exclude='public/assets/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.log' \
    --exclude='*.db' \
    --exclude='*.pid' \
    --exclude='*.tmp' \
    --exclude='node_modules/' \
    --exclude='dist/' \
    --exclude='build/' \
    --exclude='.DS_Store' \
    --exclude='deploy.sh' \
    "$REPO_DIR/" "$DEPLOY_DIR/"

echo ""
echo "[DEPLOY] Sync complete."
echo ""
echo "[INFO] Files intentionally NOT synced (preserved on server):"
echo "        .env, data/, config/, static/, public/assets/"
echo ""
echo "[INFO] To apply changes, restart the container:"
echo "        docker compose -f $DEPLOY_DIR/docker/compose.yaml up -d --force-recreate"
