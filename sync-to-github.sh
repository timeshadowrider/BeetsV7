#!/usr/bin/env bash
# sync-to-github.sh
# Run this ON THE SERVER at:
#   /srv/dev-disk-by-uuid-306c14f2-0239-4b1e-8775-915dfdd88bd0/NVME/Docket_Configs/Beets-v7
#
# It commits any uncommitted changes and pushes to the claude/review-beetv7-CZJLf branch.

set -euo pipefail

REPO="/srv/dev-disk-by-uuid-306c14f2-0239-4b1e-8775-915dfdd88bd0/NVME/Docket_Configs/Beets-v7"
TARGET_BRANCH="claude/review-beetv7-CZJLf"

cd "$REPO"

echo "[SYNC] Repo: $REPO"
echo "[SYNC] Branch: $TARGET_BRANCH"
echo ""

# Show what's different
echo "[SYNC] Current git status:"
git status --short
echo ""

# Stage everything except secrets and runtime data
git add \
    backend/ \
    scripts/ \
    frontend/ \
    docker/Dockerfile \
    docker/compose.yaml \
    docker/.env.example \
    config/config.yaml \
    entrypoint.sh \
    run_all.sh \
    truncate_verbose_log.sh \
    readme.md \
    2>/dev/null || true

# Only commit if there's something staged
if git diff --cached --quiet; then
    echo "[SYNC] Nothing new to commit — repo is already up to date."
else
    echo "[SYNC] Committing staged changes..."
    git commit -m "sync: pull live server state into repo"
fi

echo "[SYNC] Pushing to origin/$TARGET_BRANCH ..."
git push -u origin "$TARGET_BRANCH"

echo ""
echo "[SYNC] Done. Check GitHub for the updated branch."
