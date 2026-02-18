#!/usr/bin/env bash
#
# truncate_verbose_log.sh
# Truncates pipeline_verbose.log when it exceeds a size threshold,
# keeping only the last N hours of entries.
#
# Usage:
#   ./truncate_verbose_log.sh [log_file] [max_size_mb] [keep_hours]
#
# Defaults:
#   log_file     = <script_dir>/data/pipeline_verbose.log
#   max_size_mb  = 50
#   keep_hours   = 24
#
# Exit codes:
#   0 = success (truncated or skipped because under threshold)
#   1 = error
#
set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="${SCRIPT_DIR}/data/pipeline_verbose.log"
MAX_SIZE_MB=1
KEEP_HOURS=24

# ── Argument overrides ───────────────────────────────────────────────────────
if [ $# -ge 1 ]; then LOG="$1"; fi
if [ $# -ge 2 ]; then MAX_SIZE_MB="$2"; fi
if [ $# -ge 3 ]; then KEEP_HOURS="$3"; fi

# TMP derived after LOG is finalised
TMP="${LOG}.tmp"
MAX_SIZE_BYTES=$(( MAX_SIZE_MB * 1024 * 1024 ))

# ── Helpers ──────────────────────────────────────────────────────────────────
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [TRUNCATE] $*"; }
err()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [TRUNCATE] ERROR: $*" >&2; }

# ── Checks ───────────────────────────────────────────────────────────────────
if [ ! -f "$LOG" ]; then
    err "Log file not found: $LOG"
    exit 1
fi

if [ ! -s "$LOG" ]; then
    log "Log file is empty, nothing to do: $LOG"
    exit 0
fi

# ── Size check ───────────────────────────────────────────────────────────────
CURRENT_SIZE=$(stat -c%s "$LOG")
CURRENT_SIZE_MB=$(( CURRENT_SIZE / 1024 / 1024 ))

if [ "$CURRENT_SIZE" -lt "$MAX_SIZE_BYTES" ]; then
    log "Log is ${CURRENT_SIZE_MB}MB / ${MAX_SIZE_MB}MB threshold — no truncation needed."
    exit 0
fi

log "Log is ${CURRENT_SIZE_MB}MB — exceeds ${MAX_SIZE_MB}MB threshold. Truncating..."

# ── Truncate ─────────────────────────────────────────────────────────────────
CUTOFF=$(date -d "$KEEP_HOURS hours ago" +"%Y-%m-%d %H:%M:%S")
log "Keeping entries newer than: $CUTOFF"

if command -v gawk &>/dev/null; then
    gawk -v cutoff="$CUTOFF" '
        match($0, /\[([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})\]/, m) {
            if (m[1] >= cutoff) print
        }
    ' "$LOG" > "$TMP"
else
    awk -v cutoff="$CUTOFF" '
        {
            s = index($0, "[")
            if (s > 0) {
                ts = substr($0, s+1, 19)
                if (ts ~ /^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$/) {
                    if (ts >= cutoff) print
                }
            }
        }
    ' "$LOG" > "$TMP"
fi

MATCHED=$(wc -l < "$TMP" 2>/dev/null || echo 0)

# ── Safety checks ────────────────────────────────────────────────────────────
if [ ! -s "$TMP" ]; then
    err "Temp file is empty after filtering — aborting to protect $LOG"
    err "Check timestamp format. First 3 lines:"
    head -3 "$LOG" >&2
    rm -f "$TMP"
    exit 1
fi

NEW_SIZE=$(stat -c%s "$TMP")
NEW_SIZE_MB=$(( NEW_SIZE / 1024 / 1024 ))

# Refuse if the result is suspiciously large (>90% of original) — likely a format mismatch
THRESHOLD_PCT=90
RATIO=$(( NEW_SIZE * 100 / CURRENT_SIZE ))
if [ "$RATIO" -ge "$THRESHOLD_PCT" ]; then
    err "Filtered file is ${RATIO}% of original — timestamp format may not match. Aborting."
    err "Check timestamp format. First 3 lines:"
    head -3 "$LOG" >&2
    rm -f "$TMP"
    exit 1
fi

# ── Commit ───────────────────────────────────────────────────────────────────
mv "$TMP" "$LOG"
log "Done. ${CURRENT_SIZE_MB}MB → ${NEW_SIZE_MB}MB | ${MATCHED} lines retained (last ${KEEP_HOURS}h)"
exit 0
