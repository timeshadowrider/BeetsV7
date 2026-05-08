#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Beets Metadata Refresh Script
Runs all metadata plugins on a schedule to keep library up-to-date.

Changes from original:
- Added fingerprint step before mbsync so as-is imports from the previous
  day get AcoustID-matched before mbsync tries to sync them
- Added orphan duplicate cleanup step (removes .1.flac, .1.mp3 etc DB records
  where the file no longer exists on disk -- these are created when beets
  imports a duplicate and appends .1 to avoid overwriting, then the pipeline
  moves or deletes the original leaving a stale DB record that crashes chroma)
"""

import subprocess
import sqlite3
import os
import re
import time
from datetime import datetime
from pathlib import Path
import logging

# Configure logging
LOG_FILE = Path("/data/metadata_refresh.log")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

LIBRARY_DB = Path("/data/library.db")


def run_beet_command(command: str, description: str, timeout: int = 3600):
    """
    Run a beet command and log the result.

    Args:
        command: Beet command to run (e.g., "beet fetchart")
        description: Human-readable description
        timeout: Command timeout in seconds (default: 1 hour)

    Returns:
        bool: True if successful, False otherwise
    """
    logger.info(f"[START] {description}")
    logger.info(f"[CMD] {command}")

    start_time = time.time()

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )

        elapsed = time.time() - start_time

        if result.returncode == 0:
            logger.info(f"[SUCCESS] {description} (took {elapsed:.1f}s)")
            if result.stdout.strip():
                logger.debug(f"[OUTPUT] {result.stdout[:500]}")
            return True
        else:
            logger.warning(f"[FAILED] {description} (exit code {result.returncode})")
            if result.stderr.strip():
                logger.error(f"[ERROR] {result.stderr[:500]}")
            return False

    except subprocess.TimeoutExpired:
        logger.error(f"[TIMEOUT] {description} exceeded {timeout}s")
        return False
    except Exception as e:
        logger.error(f"[ERROR] {description}: {e}")
        return False


def cleanup_orphaned_duplicates():
    """
    Remove DB records for duplicate files that no longer exist on disk.

    When beets imports a file that would overwrite an existing one, it appends
    a numeric suffix to avoid collision: track.flac -> track.1.flac, track.2.flac
    etc. If the pipeline later moves or deletes the original, these .1/.2 records
    become orphans -- the DB record exists but the file is gone. The chroma
    fingerprint command then crashes with FileNotFoundError on every run.

    This step finds all such orphaned records and removes them from the DB.
    It also reports any .1/.2 files that DO exist on disk so you can review
    them manually as genuine duplicates.
    """
    logger.info("=" * 60)
    logger.info("CLEANING UP ORPHANED DUPLICATE RECORDS")
    logger.info("=" * 60)

    if not LIBRARY_DB.exists():
        logger.warning(f"[CLEANUP] Library DB not found: {LIBRARY_DB}")
        return

    try:
        conn = sqlite3.connect(str(LIBRARY_DB))
        rows = conn.execute("SELECT id, path FROM items").fetchall()

        orphaned = []
        live_duplicates = []

        for rid, path in rows:
            p = path.decode() if isinstance(path, bytes) else path
            # Strip surrounding quotes that beets sometimes stores
            p_clean = p.strip("'\"")

            # Match .1.flac, .2.mp3, .1.m4a etc
            if re.search(r'\.\d+\.(flac|mp3|m4a|ogg|wav|aac)$', p_clean, re.IGNORECASE):
                if not os.path.exists(p_clean):
                    orphaned.append((rid, p_clean))
                else:
                    live_duplicates.append(p_clean)

        # Report live duplicates for manual review
        if live_duplicates:
            logger.warning(f"[CLEANUP] Found {len(live_duplicates)} live duplicate files (not removed -- review manually):")
            for p in live_duplicates:
                logger.warning(f"  LIVE DUPLICATE: {p}")

        # Remove orphaned records
        if orphaned:
            logger.info(f"[CLEANUP] Removing {len(orphaned)} orphaned DB records:")
            for rid, p in orphaned:
                logger.info(f"  REMOVING id={rid}: {p}")

            conn.executemany("DELETE FROM items WHERE id=?", [(r,) for r, _ in orphaned])
            conn.commit()
            logger.info(f"[CLEANUP] Done -- removed {len(orphaned)} orphaned records")
        else:
            logger.info("[CLEANUP] No orphaned duplicate records found")

        conn.close()

    except Exception as e:
        logger.error(f"[CLEANUP] Error during orphan cleanup: {e}")


def fingerprint_unmatched():
    """
    Run AcoustID fingerprinting on tracks that have no MusicBrainz recording ID.

    As-is imports (tracks that didn't match during import) have no mb_trackid.
    Running fingerprint before mbsync gives those tracks an ID so mbsync can
    actually sync their metadata rather than skipping them with
    'Skipping album with no mb_albumid'.
    """
    logger.info("=" * 60)
    logger.info("FINGERPRINTING UNMATCHED TRACKS")
    logger.info("=" * 60)

    run_beet_command(
        'beet fingerprint mb_trackid:""',
        "Fingerprint tracks missing MusicBrainz ID (AcoustID lookup)",
        timeout=7200  # fingerprinting can take a while for large libraries
    )


def sync_musicbrainz():
    """Sync metadata with MusicBrainz database."""
    logger.info("=" * 60)
    logger.info("SYNCING WITH MUSICBRAINZ")
    logger.info("=" * 60)

    run_beet_command(
        "beet mbsync",
        "Sync metadata with MusicBrainz"
    )


def fetch_missing_artwork():
    """Fetch missing album artwork from various sources."""
    logger.info("=" * 60)
    logger.info("FETCHING MISSING ARTWORK")
    logger.info("=" * 60)

    run_beet_command(
        "beet fetchart",
        "Fetch missing album art"
    )


def embed_artwork():
    """Embed album artwork into audio files."""
    logger.info("=" * 60)
    logger.info("EMBEDDING ARTWORK")
    logger.info("=" * 60)

    run_beet_command(
        "beet embedart -y",
        "Embed artwork into files"
    )


def fetch_lyrics():
    """Fetch missing lyrics."""
    logger.info("=" * 60)
    logger.info("FETCHING LYRICS")
    logger.info("=" * 60)

    run_beet_command(
        "beet lyrics",
        "Fetch missing lyrics"
    )


def update_genres():
    """Update genre tags from Last.fm."""
    logger.info("=" * 60)
    logger.info("UPDATING GENRES")
    logger.info("=" * 60)

    run_beet_command(
        "beet lastgenre",
        "Update genre tags from Last.fm"
    )


def scrub_metadata():
    """Clean and normalize metadata tags."""
    logger.info("=" * 60)
    logger.info("SCRUBBING METADATA")
    logger.info("=" * 60)

    run_beet_command(
        "beet scrub",
        "Scrub and normalize metadata"
    )


def move_library():
    """
    Move any files whose path doesn't match the current path template.
    Runs after mbsync in case metadata changes affect folder/file names.
    """
    logger.info("=" * 60)
    logger.info("MOVING FILES TO CORRECT PATHS")
    logger.info("=" * 60)

    run_beet_command(
        "beet move",
        "Move files to match current path template"
    )


def generate_smart_playlists():
    """Generate smart playlists based on queries."""
    logger.info("=" * 60)
    logger.info("GENERATING SMART PLAYLISTS")
    logger.info("=" * 60)

    run_beet_command(
        "beet splupdate",
        "Update smart playlists"
    )


def update_plex():
    """Trigger Plex library update."""
    logger.info("=" * 60)
    logger.info("UPDATING PLEX")
    logger.info("=" * 60)

    run_beet_command(
        "beet plexupdate",
        "Trigger Plex library update"
    )


def update_mpd():
    """Trigger MPD database update."""
    logger.info("=" * 60)
    logger.info("UPDATING MPD")
    logger.info("=" * 60)

    run_beet_command(
        "beet mpdupdate",
        "Trigger MPD database update"
    )


def run_full_refresh():
    """
    Run complete metadata refresh cycle.

    Order of operations:
    0. Cleanup orphaned .1.flac/.1.mp3 DB records (prevents chroma crash)
    1. Fingerprint unmatched tracks (AcoustID -- gives mb_trackid to as-is imports)
    2. Sync with MusicBrainz (now has IDs for previously unmatched tracks too)
    3. Move files to correct paths (tags may have changed from mbsync)
    4. Fetch missing artwork
    5. Embed artwork into files
    6. Fetch missing lyrics
    7. Update genres
    8. Scrub/clean metadata
    9. Generate smart playlists
    10. Notify media servers (Plex, MPD)
    """
    start_time = time.time()

    logger.info("=" * 60)
    logger.info("  BEETS METADATA REFRESH STARTED")
    logger.info(f"  Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Phase 0: Housekeeping
    logger.info("\n>>> PHASE 0: HOUSEKEEPING <<<\n")
    cleanup_orphaned_duplicates()

    # Phase 1: Metadata Updates
    logger.info("\n>>> PHASE 1: METADATA UPDATES <<<\n")
    fingerprint_unmatched()
    sync_musicbrainz()
    move_library()

    # Phase 2: Artwork
    logger.info("\n>>> PHASE 2: ARTWORK <<<\n")
    fetch_missing_artwork()
    embed_artwork()

    # Phase 3: Lyrics & Genres
    logger.info("\n>>> PHASE 3: LYRICS & GENRES <<<\n")
    fetch_lyrics()
    update_genres()

    # Phase 4: Cleanup
    logger.info("\n>>> PHASE 4: CLEANUP <<<\n")
    scrub_metadata()

    # Phase 5: Playlists & Notifications
    logger.info("\n>>> PHASE 5: PLAYLISTS & NOTIFICATIONS <<<\n")
    generate_smart_playlists()
    update_plex()
    update_mpd()

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("  METADATA REFRESH COMPLETED")
    logger.info(f"  Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  Total time: {elapsed / 60:.1f} minutes")
    logger.info("=" * 60)


def run_quick_refresh():
    """
    Run quick refresh - housekeeping + artwork, lyrics, and server updates.
    Skips fingerprinting and mbsync (slow) for more frequent interval runs.
    """
    start_time = time.time()

    logger.info(">>> QUICK REFRESH STARTED <<<")

    cleanup_orphaned_duplicates()
    fetch_missing_artwork()
    embed_artwork()
    fetch_lyrics()
    generate_smart_playlists()
    update_plex()
    update_mpd()

    elapsed = time.time() - start_time
    logger.info(f">>> QUICK REFRESH COMPLETED ({elapsed / 60:.1f} minutes) <<<")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        run_quick_refresh()
    else:
        run_full_refresh()