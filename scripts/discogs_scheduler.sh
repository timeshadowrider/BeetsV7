#!/bin/bash
# discogs_scheduler.sh
# Add to crontab with: crontab -e
# Runs bulk Discogs tagger weekly on Sunday at 3am
#
# To install:
#   docker cp discogs_scheduler.sh beetsV7:/app/scripts/discogs_scheduler.sh
#   chmod +x /app/scripts/discogs_scheduler.sh
#   Then add to crontab inside container:
#   docker exec -it beetsV7 crontab -l > /tmp/crontab.txt
#   echo "0 3 * * 0 /app/scripts/discogs_scheduler.sh >> /data/discogs_scheduler.log 2>&1" >> /tmp/crontab.txt
#   docker exec -it beetsV7 crontab /tmp/crontab.txt

SCRIPT="/app/scripts/discogs_bulk_tag.py"
LOG="/data/discogs_bulk_tag.log"
LOCKFILE="/tmp/discogs_bulk_tag.lock"

# Prevent overlapping runs
if [ -f "$LOCKFILE" ]; then
    echo "$(date): Already running, exiting." >> "$LOG"
    exit 0
fi

touch "$LOCKFILE"
trap "rm -f $LOCKFILE" EXIT

echo "$(date): Starting scheduled Discogs bulk tag run" >> "$LOG"

# Run with --move to rename folders after updating
python3 "$SCRIPT" --move >> "$LOG" 2>&1

echo "$(date): Scheduled run complete" >> "$LOG"